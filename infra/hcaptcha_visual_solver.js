/**
 * hCaptcha Visual Solver v2 — Extract image URLs + screenshots for CLIP
 * 
 * Improvements over v1:
 *   - Downloads images from background-image URLs (better quality than screenshots)
 *   - Falls back to screenshots if URL extraction fails
 *   - Extracts example/reference image separately
 *   - Supports multiple challenge rounds (hCaptcha often asks 2-3 rounds)
 *   - Better frame detection
 * 
 * Protocolo stdout (JSON por linha):
 *   → {"status":"auto_solved","token":"..."}
 *   → {"status":"challenge","prompt":"...","example":"/path/example.png","images":["/path/0.png",...],"round":1}
 *   ← {"clicks":[0,2,5]}
 *   → {"status":"solved","token":"..."} | {"status":"failed","error":"..."}
 * 
 * Uso: DISPLAY=:121 NODE_PATH=/home/ramza/node_modules node hcaptcha_visual_solver.js <url>
 */
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');
const https = require('https');
const readline = require('readline');

puppeteer.use(StealthPlugin());

const TARGET_URL = process.argv[2] || '';
const CHROME = '/usr/bin/google-chrome';
const MAX_ROUNDS = 5;

function log(msg) { process.stderr.write(`[HCVIS][${new Date().toTimeString().slice(0,8)}] ${msg}\n`); }
function respond(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }

function downloadImage(url, destPath) {
    return new Promise((resolve, reject) => {
        const file = fs.createWriteStream(destPath);
        https.get(url, (resp) => {
            if (resp.statusCode === 301 || resp.statusCode === 302) {
                https.get(resp.headers.location, (resp2) => {
                    resp2.pipe(file);
                    file.on('finish', () => { file.close(); resolve(true); });
                }).on('error', () => resolve(false));
                return;
            }
            resp.pipe(file);
            file.on('finish', () => { file.close(); resolve(true); });
        }).on('error', () => resolve(false));
    });
}

function waitForLine(rl, timeoutMs = 45000) {
    return new Promise((resolve) => {
        const timer = setTimeout(() => resolve(null), timeoutMs);
        rl.once('line', (line) => {
            clearTimeout(timer);
            try { resolve(JSON.parse(line.trim())); } catch { resolve(null); }
        });
    });
}

(async () => {
    if (!TARGET_URL) { process.exit(1); }

    const browser = await puppeteer.launch({
        headless: false, executablePath: CHROME,
        args: ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--window-size=1200,900',
               '--no-first-run','--disable-extensions','--disable-sync','--mute-audio',
               '--disable-infobars','--password-store=basic',
               '--disable-blink-features=AutomationControlled'],
        ignoreDefaultArgs: ['--enable-automation'],
        defaultViewport: null, ignoreHTTPSErrors: true,
    });

    const page = (await browser.pages())[0] || await browser.newPage();
    log(`Navigating to ${TARGET_URL}`);
    await page.goto(TARGET_URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await new Promise(r => setTimeout(r, 3000));

    // Find hCaptcha checkbox frame
    let cbFrame = null;
    for (const f of page.frames()) {
        const url = f.url();
        if (!url.includes('hcaptcha') && !url.includes('newassets')) continue;
        try {
            const has = await f.evaluate(() => !!document.querySelector('#checkbox'));
            if (has) { cbFrame = f; break; }
        } catch {}
    }

    if (!cbFrame) {
        log('No hCaptcha checkbox found');
        respond({ status: 'error', error: 'no_hcaptcha' });
        await browser.close(); process.exit(1);
    }

    await cbFrame.click('#checkbox');
    log('Clicked checkbox');
    await new Promise(r => setTimeout(r, 5000));

    // Check auto-solve
    let token = await page.evaluate(() => {
        const t = document.querySelector('textarea[name="h-captcha-response"]');
        return t && t.value.length > 20 ? t.value : '';
    });
    if (token) {
        respond({ status: 'auto_solved', token });
        await browser.close(); process.exit(0);
    }

    // Setup readline for Python communication
    const rl = readline.createInterface({ input: process.stdin });

    const imgDir = `/tmp/hcaptcha_${Date.now()}`;
    fs.mkdirSync(imgDir, { recursive: true });

    for (let round = 1; round <= MAX_ROUNDS; round++) {
        log(`--- Round ${round} ---`);

        // Find challenge frame
        let chFrame = null;
        for (const f of page.frames()) {
            const url = f.url();
            if (!url.includes('hcaptcha') && !url.includes('newassets')) continue;
            try {
                const has = await f.evaluate(() => !!document.querySelector('.task-grid, .challenge-container'));
                if (has) { chFrame = f; break; }
            } catch {}
        }

        if (!chFrame) {
            // Maybe already solved after previous round?
            token = await page.evaluate(() => {
                const t = document.querySelector('textarea[name="h-captcha-response"]');
                return t && t.value.length > 20 ? t.value : '';
            });
            if (token) {
                respond({ status: 'solved', token });
                log(`Solved after ${round - 1} rounds! Token: ${token.length} chars`);
                break;
            }
            log('No challenge frame found');
            respond({ status: 'error', error: 'no_challenge_frame' });
            break;
        }

        // Extract prompt
        const prompt = await chFrame.evaluate(() => {
            const el = document.querySelector('.prompt-text');
            return el ? el.textContent.trim() : '';
        });
        log(`Prompt: "${prompt}"`);

        // Extract example image URL from prompt area
        const exampleUrl = await chFrame.evaluate(() => {
            // The example image is inside .prompt-padding > .image with background-image
            const el = document.querySelector('.prompt-padding .image, .challenge-example .image');
            if (!el) return '';
            const bg = getComputedStyle(el).backgroundImage;
            const m = bg.match(/url\("?(.+?)"?\)/);
            return m ? m[1] : '';
        });

        let examplePath = '';
        if (exampleUrl && exampleUrl.startsWith('http')) {
            examplePath = `${imgDir}/r${round}_example.png`;
            const ok = await downloadImage(exampleUrl, examplePath);
            if (!ok) {
                log('Failed to download example image, falling back to screenshot');
                examplePath = '';
            } else {
                log(`Example image downloaded: ${exampleUrl.substring(0, 80)}...`);
            }
        }

        // If download failed, try screenshot of example area
        if (!examplePath) {
            const exBox = await chFrame.evaluate(() => {
                const el = document.querySelector('.prompt-padding .image, .challenge-example .image');
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return { x: r.x, y: r.y, w: r.width, h: r.height };
            });
            if (exBox && exBox.w > 10) {
                examplePath = `${imgDir}/r${round}_example.png`;
                const frameEl = await page.$('iframe[title*="hCaptcha"], iframe[data-hcaptcha-widget-id]');
                let ox = 0, oy = 0;
                if (frameEl) { const fb = await frameEl.boundingBox(); if (fb) { ox = fb.x; oy = fb.y; } }
                await page.screenshot({ path: examplePath, clip: { x: ox+exBox.x, y: oy+exBox.y, width: exBox.w, height: exBox.h } });
                log('Example captured via screenshot');
            }
        }

        // Extract cell image URLs
        const cellData = await chFrame.evaluate(() => {
            const cells = document.querySelectorAll('.task-image');
            const results = [];
            cells.forEach((cell, i) => {
                const imgEl = cell.querySelector('.image');
                let bgUrl = '';
                if (imgEl) {
                    const bg = getComputedStyle(imgEl).backgroundImage;
                    const m = bg.match(/url\("?(.+?)"?\)/);
                    bgUrl = m ? m[1] : '';
                }
                const r = cell.getBoundingClientRect();
                results.push({
                    idx: i,
                    url: bgUrl,
                    x: r.x, y: r.y, w: r.width, h: r.height,
                });
            });
            return results;
        });

        log(`Grid cells: ${cellData.length}`);

        // Download or screenshot each cell
        const imgPaths = [];
        for (const cell of cellData) {
            const cellPath = `${imgDir}/r${round}_cell_${cell.idx}.png`;
            let saved = false;

            // Try download from URL first
            if (cell.url && cell.url.startsWith('http')) {
                saved = await downloadImage(cell.url, cellPath);
                if (saved) {
                    imgPaths.push(cellPath);
                    continue;
                }
            }

            // Fallback: screenshot
            if (cell.w > 10) {
                const frameEl = await page.$('iframe[title*="hCaptcha"], iframe[data-hcaptcha-widget-id]');
                let ox = 0, oy = 0;
                if (frameEl) { const fb = await frameEl.boundingBox(); if (fb) { ox = fb.x; oy = fb.y; } }
                try {
                    await page.screenshot({ path: cellPath, clip: { x: ox+cell.x, y: oy+cell.y, width: cell.w, height: cell.h } });
                    imgPaths.push(cellPath);
                    saved = true;
                } catch (e) {
                    log(`Screenshot failed for cell ${cell.idx}: ${e.message}`);
                }
            }

            if (!saved) {
                imgPaths.push(''); // placeholder
            }
        }

        log(`Images ready: ${imgPaths.filter(p => p).length}/${cellData.length}`);

        // Send challenge to Python
        respond({
            status: 'challenge',
            prompt,
            example: examplePath,
            images: imgPaths,
            cell_count: cellData.length,
            round,
        });

        // Wait for Python response
        const msg = await waitForLine(rl, 45000);
        if (!msg || !msg.clicks || msg.clicks.length === 0) {
            log('No clicks from classifier, skipping this round');
            // Click skip button if available
            await chFrame.evaluate(() => {
                const btn = document.querySelector('.button-submit');
                if (btn) btn.click();
            });
            await new Promise(r => setTimeout(r, 3000));
            continue;
        }

        log(`Clicking cells: ${msg.clicks}`);

        // Click indicated cells
        for (const idx of msg.clicks) {
            await chFrame.evaluate((i) => {
                const cells = document.querySelectorAll('.task-image');
                if (i < cells.length) cells[i].click();
            }, idx);
            await new Promise(r => setTimeout(r, 250 + Math.random() * 200));
        }

        // Wait a bit then click verify/submit
        await new Promise(r => setTimeout(r, 400 + Math.random() * 300));
        const submitText = await chFrame.evaluate(() => {
            const btn = document.querySelector('.button-submit');
            if (btn) {
                btn.click();
                return btn.textContent.trim();
            }
            return 'no_button';
        });
        log(`Clicked submit (text: "${submitText}")`);

        // Wait for result — either new challenge or token
        await new Promise(r => setTimeout(r, 4000));

        // Check if we got a token
        token = await page.evaluate(() => {
            const t = document.querySelector('textarea[name="h-captcha-response"]');
            return t && t.value.length > 20 ? t.value : '';
        });
        if (token) {
            respond({ status: 'solved', token });
            log(`Solved in round ${round}! Token: ${token.length} chars`);
            break;
        }

        // No token — might be another round or failure
        log(`Round ${round} done, no token yet. Checking for new challenge...`);
        await new Promise(r => setTimeout(r, 2000));
    }

    if (!token) {
        respond({ status: 'failed', error: 'max_rounds_exceeded' });
        log(`Failed after ${MAX_ROUNDS} rounds`);
    }

    // Cleanup
    rl.close();
    try { fs.rmSync(imgDir, { recursive: true }); } catch {}
    await browser.close();
    process.exit(token ? 0 : 1);
})().catch(e => {
    log('Fatal: ' + e.message);
    respond({ status: 'error', error: e.message });
    process.exit(1);
});

/**
 * CPF Receita Full Solver — hCaptcha + form submit in same browser session
 *
 * Protocolo stdout (JSON por linha):
 *   → {"status":"challenge","prompt":"...","example":"/path","images":[...],"round":1}
 *   ← {"clicks":[0,2,5]}
 *   → {"status":"sucesso","html":"...","nome":"...","situacao":"..."}
 *   → {"status":"erro","error":"..."}
 *
 * Args: node cpf_receita_full_solver.js <cpf_formatado> <data_nascimento>
 */
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');
const https = require('https');
const readline = require('readline');

puppeteer.use(StealthPlugin());

const CPF = process.argv[2] || '';
const DATA_NASC = process.argv[3] || '';
const CHROME = '/usr/bin/google-chrome';
const MAX_ROUNDS = 5;
const CPF_URL = 'https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/consultapublica.asp';

function log(msg) { process.stderr.write(`[RCPF][${new Date().toTimeString().slice(0,8)}] ${msg}\n`); }
function respond(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }

function downloadImage(url, destPath) {
    return new Promise((resolve) => {
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
    if (!CPF || !DATA_NASC) {
        respond({ status: 'erro', error: 'args: cpf data_nascimento' });
        process.exit(1);
    }

    log(`CPF: ${CPF}, Nascimento: ${DATA_NASC}`);

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

    log('Navigating to Receita CPF page...');
    await page.goto(CPF_URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await new Promise(r => setTimeout(r, 2000));

    // Fill form fields using keyboard typing (triggers all native events)
    log('Filling form...');
    // Type CPF (digits only, the onblur will format it)
    const cpfDigits = CPF.replace(/\D/g, '');
    await page.click('#txtCPF');
    await page.evaluate(() => { document.querySelector('#txtCPF').value = ''; });
    await page.type('#txtCPF', cpfDigits, { delay: 30 });
    // Trigger onblur to format
    await page.evaluate(() => {
        const el = document.querySelector('#txtCPF');
        el.dispatchEvent(new Event('blur', { bubbles: true }));
        if (typeof FG_FormatarCPF === 'function') FG_FormatarCPF('txtCPF');
    });

    // Type date (digits only, onblur will format)
    const dataDigits = DATA_NASC.replace(/\D/g, '');
    await page.click('#txtDataNascimento');
    await page.evaluate(() => { document.querySelector('#txtDataNascimento').value = ''; });
    await page.type('#txtDataNascimento', dataDigits, { delay: 30 });
    await page.evaluate(() => {
        const el = document.querySelector('#txtDataNascimento');
        el.dispatchEvent(new Event('blur', { bubbles: true }));
        if (typeof FG_FormatarData === 'function') FG_FormatarData('txtDataNascimento');
    });
    log('Form filled via typing');

    await new Promise(r => setTimeout(r, 1000));

    // Find hCaptcha checkbox frame and click
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
        respond({ status: 'erro', error: 'no_hcaptcha' });
        await browser.close(); process.exit(1);
    }

    await cbFrame.click('#checkbox');
    log('Clicked hCaptcha checkbox');
    await new Promise(r => setTimeout(r, 5000));

    // Check auto-solve
    let token = await page.evaluate(() => {
        const t = document.querySelector('textarea[name="h-captcha-response"]');
        return t && t.value.length > 20 ? t.value : '';
    });

    if (!token) {
        // Need to solve challenge via CLIP
        const rl = readline.createInterface({ input: process.stdin });
        const imgDir = `/tmp/hcaptcha_cpf_${Date.now()}`;
        fs.mkdirSync(imgDir, { recursive: true });

        for (let round = 1; round <= MAX_ROUNDS; round++) {
            log(`--- Round ${round} ---`);

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
                token = await page.evaluate(() => {
                    const t = document.querySelector('textarea[name="h-captcha-response"]');
                    return t && t.value.length > 20 ? t.value : '';
                });
                if (token) break;
                log('No challenge frame found');
                break;
            }

            const prompt = await chFrame.evaluate(() => {
                const el = document.querySelector('.prompt-text');
                return el ? el.textContent.trim() : '';
            });
            log(`Prompt: "${prompt}"`);

            // Extract example image
            const exampleUrl = await chFrame.evaluate(() => {
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
                if (!ok) examplePath = '';
            }

            // Extract cell images
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
                    results.push({ idx: i, url: bgUrl, x: r.x, y: r.y, w: r.width, h: r.height });
                });
                return results;
            });

            const imgPaths = [];
            for (const cell of cellData) {
                const cellPath = `${imgDir}/r${round}_cell_${cell.idx}.png`;
                let saved = false;
                if (cell.url && cell.url.startsWith('http')) {
                    saved = await downloadImage(cell.url, cellPath);
                    if (saved) { imgPaths.push(cellPath); continue; }
                }
                if (cell.w > 10) {
                    const frameEl = await page.$('iframe[title*="hCaptcha"], iframe[data-hcaptcha-widget-id]');
                    let ox = 0, oy = 0;
                    if (frameEl) { const fb = await frameEl.boundingBox(); if (fb) { ox = fb.x; oy = fb.y; } }
                    try {
                        await page.screenshot({ path: cellPath, clip: { x: ox+cell.x, y: oy+cell.y, width: cell.w, height: cell.h } });
                        imgPaths.push(cellPath); saved = true;
                    } catch {}
                }
                if (!saved) imgPaths.push('');
            }

            log(`Images ready: ${imgPaths.filter(p => p).length}/${cellData.length}`);

            respond({
                status: 'challenge', prompt, example: examplePath,
                images: imgPaths, cell_count: cellData.length, round,
            });

            const msg = await waitForLine(rl, 45000);
            if (!msg || !msg.clicks || msg.clicks.length === 0) {
                await chFrame.evaluate(() => {
                    const btn = document.querySelector('.button-submit');
                    if (btn) btn.click();
                });
                await new Promise(r => setTimeout(r, 3000));
                continue;
            }

            log(`Clicking cells: ${msg.clicks}`);
            for (const idx of msg.clicks) {
                await chFrame.evaluate((i) => {
                    const cells = document.querySelectorAll('.task-image');
                    if (i < cells.length) cells[i].click();
                }, idx);
                await new Promise(r => setTimeout(r, 250 + Math.random() * 200));
            }

            await new Promise(r => setTimeout(r, 400 + Math.random() * 300));
            await chFrame.evaluate(() => {
                const btn = document.querySelector('.button-submit');
                if (btn) btn.click();
            });

            await new Promise(r => setTimeout(r, 4000));

            token = await page.evaluate(() => {
                const t = document.querySelector('textarea[name="h-captcha-response"]');
                return t && t.value.length > 20 ? t.value : '';
            });
            if (token) {
                log(`Solved in round ${round}! Token: ${token.length} chars`);
                break;
            }
            log(`Round ${round} done, no token yet...`);
            await new Promise(r => setTimeout(r, 2000));
        }

        rl.close();
        try { fs.rmSync(imgDir, { recursive: true }); } catch {}
    }

    if (!token) {
        respond({ status: 'erro', error: 'hcaptcha_failed' });
        await browser.close(); process.exit(1);
    }

    log(`hCaptcha solved: ${token.length} chars`);

    // Now submit the form within the same browser session
    log('Submitting form via browser...');

    // Ensure form fields are filled and idCheckedReCaptcha is true
    const formState = await page.evaluate((cpf, dataNasc) => {
        const cpfInput = document.querySelector('#txtCPF') || document.querySelector('input[name="txtCPF"]');
        const dataInput = document.querySelector('#txtDataNascimento') || document.querySelector('input[name="txtDataNascimento"]');

        // Re-fill if empty
        if (cpfInput) cpfInput.value = cpf;
        if (dataInput) dataInput.value = dataNasc;

        // CRITICAL: set idCheckedReCaptcha to true (normally done by recaptchaCallback)
        const chk = document.querySelector('#idCheckedReCaptcha') || document.querySelector('input[name="idCheckedReCaptcha"]');
        if (chk) chk.value = "true";

        return {
            cpf: cpfInput ? cpfInput.value : 'missing',
            data: dataInput ? dataInput.value : 'missing',
            checked: chk ? chk.value : 'missing',
            hcaptchaResp: (document.querySelector('textarea[name="h-captcha-response"]') || {}).value || '',
        };
    }, CPF, DATA_NASC);
    log(`Form state: CPF=${formState.cpf}, Data=${formState.data}, Checked=${formState.checked}, hcaptcha=${formState.hcaptchaResp.length}ch`);

    // Submit the form via the Consultar button (triggers ValidarDados)
    const submitted = await page.evaluate(() => {
        const btn = document.querySelector('#id_submit');
        if (btn) {
            btn.click();
            return 'clicked: ' + btn.value;
        }
        const form = document.querySelector('#theForm') || document.querySelector('form');
        if (form) {
            form.submit();
            return 'form.submit()';
        }
        return null;
    });

    if (!submitted) {
        respond({ status: 'erro', error: 'no_submit_button' });
        await browser.close(); process.exit(1);
    }
    log(`Submitted: ${submitted}`);

    // Wait for navigation to result page
    try {
        await page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 15000 });
    } catch (e) {
        log('Navigation timeout, checking current page...');
    }
    await new Promise(r => setTimeout(r, 2000));

    // Check result
    const resultUrl = page.url();
    log(`Result URL: ${resultUrl}`);

    if (resultUrl.includes('Error=')) {
        const errMatch = resultUrl.match(/Error=(\d+)/);
        const errCode = errMatch ? errMatch[1] : '?';
        respond({ status: 'erro', error: `receita_error_${errCode}` });
        await browser.close(); process.exit(1);
    }

    // Extract full page HTML
    const html = await page.evaluate(() => document.documentElement.outerHTML);

    // Extract key fields from the page
    const data = await page.evaluate(() => {
        const getText = (label) => {
            const spans = document.querySelectorAll('span, b, td');
            for (const span of spans) {
                if (span.textContent.includes(label)) {
                    const next = span.nextElementSibling;
                    if (next) return next.textContent.trim();
                    // Check parent's next sibling
                    const parent = span.parentElement;
                    if (parent && parent.nextElementSibling) {
                        return parent.nextElementSibling.textContent.trim();
                    }
                }
            }
            return '';
        };

        return {
            nome: getText('Nome') || getText('Nome da Pessoa'),
            situacao: getText('Cadastral') || getText('Situa'),
            inscricao: getText('Inscri'),
            digito: getText('gito'),
        };
    });

    log(`Result: nome=${data.nome}, situacao=${data.situacao}`);

    // Save HTML to temp file
    const htmlPath = `/tmp/cpf_result_${Date.now()}.html`;
    fs.writeFileSync(htmlPath, html, 'utf-8');

    respond({
        status: 'sucesso',
        nome: data.nome,
        situacao: data.situacao,
        inscricao: data.inscricao,
        digito: data.digito,
        html_path: htmlPath,
        url: resultUrl,
    });

    await browser.close();
    process.exit(0);
})().catch(e => {
    log('Fatal: ' + e.message);
    respond({ status: 'erro', error: e.message });
    process.exit(1);
});

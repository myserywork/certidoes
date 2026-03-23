/**
 * AWS WAF Audio Solver — Full Local (Puppeteer-stealth + Whisper)
 * 
 * Fluxo:
 *   1. Abre página com WAF captcha
 *   2. Clica "Begin"
 *   3. Clica botão de audio
 *   4. Clica "Play Audio" e captura audio base64
 *   5. Salva audio pra Whisper transcrever (via Python stdin/stdout)
 *   6. Digita resposta → Confirm
 *   7. Se validado, captura aws-waf-token cookie
 * 
 * Protocolo stdout (JSON por linha):
 *   → {"status":"no_captcha"}                              # Sem WAF captcha
 *   → {"status":"audio_challenge","audio_file":"/tmp/..."}  # Audio pra Whisper
 *   ← {"answer":"texto"}                                    # Python responde
 *   → {"status":"solved","cookie":"aws-waf-token=..."}     # Sucesso
 *   → {"status":"failed","error":"..."}                     # Falha
 * 
 * Uso: DISPLAY=:121 NODE_PATH=/home/ramza/node_modules node aws_waf_audio_solver.js <url>
 */
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');
const readline = require('readline');

puppeteer.use(StealthPlugin());

const TARGET_URL = process.argv[2] || '';
const CHROME = process.platform === 'win32' ? null : '/usr/bin/google-chrome';

function log(msg) { process.stderr.write(`[AWSWAF][${new Date().toTimeString().slice(0,8)}] ${msg}\n`); }
function respond(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }

(async () => {
    if (!TARGET_URL) {
        log('Usage: node aws_waf_audio_solver.js <url>');
        process.exit(1);
    }

    log('Launching stealth Chrome...');
    const browser = await puppeteer.launch({
        headless: process.platform === 'win32' ? 'new' : false,
        ...(CHROME ? {executablePath: CHROME} : {}),
        args: [
            '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
            '--window-size=1200,800', '--no-first-run', '--disable-extensions',
            '--disable-sync', '--mute-audio', '--disable-infobars',
            '--password-store=basic',
            '--disable-blink-features=AutomationControlled',
        ],
        ignoreDefaultArgs: ['--enable-automation'],
        defaultViewport: null,
        ignoreHTTPSErrors: true,
    });

    const page = (await browser.pages())[0] || await browser.newPage();

    log(`Navigating to ${TARGET_URL}`);
    const resp = await page.goto(TARGET_URL, { waitUntil: 'networkidle2', timeout: 30000 });
    log(`Status: ${resp.status()}, Title: ${await page.title()}`);

    // Check if WAF captcha page
    const hasGoku = await page.evaluate(() => typeof window.gokuProps !== 'undefined');
    if (!hasGoku) {
        log('No AWS WAF captcha detected — page loaded normally');
        respond({ status: 'no_captcha' });
        await browser.close();
        process.exit(0);
    }

    await new Promise(r => setTimeout(r, 2000));

    // Click "Begin"
    log('Clicking Begin...');
    await page.evaluate(() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            if (b.textContent.trim() === 'Begin') { b.click(); return; }
        }
    });
    await new Promise(r => setTimeout(r, 3000));

    // Click audio button
    log('Clicking audio button...');
    const audioClicked = await page.evaluate(() => {
        const btns = document.querySelectorAll('button.btn-icon, button');
        for (const b of btns) {
            const img = b.querySelector('img');
            if (img && img.alt && img.alt.includes('audio')) {
                b.click();
                return true;
            }
        }
        return false;
    });

    if (!audioClicked) {
        log('No audio button found');
        respond({ status: 'error', error: 'no_audio_button' });
        await browser.close();
        process.exit(1);
    }

    await new Promise(r => setTimeout(r, 3000));

    // Click "Play Audio" button
    log('Clicking Play Audio...');
    await page.evaluate(() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            if (b.textContent.includes('Play') || b.textContent.includes('play')) {
                b.click();
                return;
            }
        }
    });
    await new Promise(r => setTimeout(r, 3000));

    // Extract audio data (base64 from audio element)
    const audioData = await page.evaluate(() => {
        const audio = document.querySelector('audio');
        if (!audio) return null;
        const src = audio.src || '';
        const source = audio.querySelector('source');
        const srcEl = source ? source.src : '';
        return src || srcEl || null;
    });

    if (!audioData) {
        log('No audio element found');
        respond({ status: 'error', error: 'no_audio_element' });
        await browser.close();
        process.exit(1);
    }

    // Save audio to file
    const audioFile = `/tmp/aws_waf_audio_${Date.now()}`;
    if (audioData.startsWith('data:audio/')) {
        // Base64 encoded
        const match = audioData.match(/^data:audio\/([^;]+);base64,(.+)$/);
        if (match) {
            const ext = match[1] === 'aac' ? 'aac' : match[1] === 'mpeg' ? 'mp3' : match[1];
            const filePath = `${audioFile}.${ext}`;
            const buffer = Buffer.from(match[2], 'base64');
            fs.writeFileSync(filePath, buffer);
            log(`Audio saved: ${filePath} (${buffer.length} bytes, format: ${ext})`);

            // Send to Python for Whisper
            respond({ status: 'audio_challenge', audio_file: filePath });
        } else {
            log('Could not parse base64 audio');
            respond({ status: 'error', error: 'audio_parse_failed' });
            await browser.close();
            process.exit(1);
        }
    } else if (audioData.startsWith('http')) {
        // URL - download it
        const { execSync } = require('child_process');
        const filePath = `${audioFile}.mp3`;
        try {
            execSync(`curl -sk -o "${filePath}" "${audioData}"`, { timeout: 15000 });
            log(`Audio downloaded: ${filePath}`);
            respond({ status: 'audio_challenge', audio_file: filePath });
        } catch (e) {
            log('Audio download failed: ' + e.message);
            respond({ status: 'error', error: 'audio_download_failed' });
            await browser.close();
            process.exit(1);
        }
    } else {
        log('Unknown audio format: ' + audioData.substring(0, 50));
        respond({ status: 'error', error: 'unknown_audio_format' });
        await browser.close();
        process.exit(1);
    }

    // Wait for answer from Python via stdin
    const rl = readline.createInterface({ input: process.stdin });
    const answerPromise = new Promise((resolve) => {
        rl.on('line', (line) => {
            try {
                const msg = JSON.parse(line.trim());
                if (msg.answer !== undefined) resolve(msg.answer);
            } catch {}
        });
        setTimeout(() => resolve(''), 30000);
    });

    const answer = await answerPromise;
    rl.close();

    if (!answer) {
        log('No answer received from Whisper');
        respond({ status: 'failed', error: 'no_whisper_answer' });
        await browser.close();
        process.exit(1);
    }

    log(`Whisper answer: "${answer}"`);

    // Type the answer in the input field
    const inputField = await page.$('input[type="text"][placeholder="Answer"]');
    if (!inputField) {
        // Try finding any text input
        const altInput = await page.$('input[type="text"]');
        if (altInput) {
            await altInput.click();
            await altInput.type(answer, { delay: 50 });
        } else {
            log('No input field found');
            respond({ status: 'failed', error: 'no_input_field' });
            await browser.close();
            process.exit(1);
        }
    } else {
        await inputField.click();
        await inputField.type(answer, { delay: 50 });
    }
    log('Answer typed');

    // Click Confirm
    await page.evaluate(() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            if (b.textContent.trim() === 'Confirm') { b.click(); return; }
        }
    });
    log('Clicked Confirm');

    // Wait for result
    await new Promise(r => setTimeout(r, 5000));

    // Check if solved - page should redirect or title should change
    const newTitle = await page.title();
    const newUrl = page.url();
    log(`After confirm — Title: "${newTitle}", URL: ${newUrl}`);

    // Check cookies
    const cookies = await page.cookies();
    const wafCookie = cookies.find(c => c.name === 'aws-waf-token');

    if (newTitle !== 'Human Verification' || !await page.evaluate(() => typeof window.gokuProps !== 'undefined')) {
        // Solved! Page changed
        const cookieStr = wafCookie ? `aws-waf-token=${wafCookie.value}` : '';
        log(`Solved! Cookie: ${cookieStr.substring(0, 50)}...`);
        respond({ status: 'solved', cookie: cookieStr, url: newUrl });
        await browser.close();
        process.exit(0);
    } else {
        log('Still on captcha page — answer may be wrong');
        respond({ status: 'failed', error: 'wrong_answer' });
        await browser.close();
        process.exit(1);
    }
})().catch(e => {
    log('Fatal: ' + e.message);
    respond({ status: 'error', error: e.message });
    process.exit(1);
});

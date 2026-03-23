/**
 * reCAPTCHA v2 Audio Solver — Full Local (Puppeteer-stealth)
 * 
 * Fluxo:
 *   1. Abre página com stealth
 *   2. Clica checkbox do reCAPTCHA
 *   3. Se challenge aparece, clica "audio"
 *   4. Baixa o MP3 do audio challenge
 *   5. Salva em /tmp para Whisper transcrever (Python faz isso)
 *   6. Recebe resposta via stdin, digita e submete
 * 
 * Protocolo stdin/stdout (JSON por linha):
 *   → {"status":"ready"}
 *   → {"status":"auto_solved","token":"..."}           # checkbox auto-passou
 *   → {"status":"audio_challenge","audio_url":"...","audio_file":"/tmp/...mp3"}
 *   ← {"answer":"texto transcrito"}                    # Python envia resposta
 *   → {"status":"solved","token":"..."} | {"status":"failed","error":"..."}
 *   → {"status":"challenge_blocked"}                   # Google bloqueou audio
 * 
 * Uso: DISPLAY=:120 NODE_PATH=/home/ramza/node_modules node recaptcha_audio_solver.js <url> <profile_dir>
 */

const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');
const readline = require('readline');

puppeteer.use(StealthPlugin());

const TARGET_URL = process.argv[2] || '';
const PROFILE = process.argv[3] || '/home/ramza/telegram_downloads/PEDRO_PROJECT/infra/profiles/recaptcha';
const POST_NAV_JS = process.argv[4] || '';  // JS to run after navigation (e.g. click a button)
const CHROME = process.platform === 'win32' ? null : '/usr/bin/google-chrome';

function log(msg) { process.stderr.write(`[RCAUDIO][${new Date().toTimeString().slice(0,8)}] ${msg}\n`); }
function respond(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }

function cleanLocks(dir) {
    for (const lk of ['SingletonLock','SingletonCookie','SingletonSocket']) {
        try { fs.unlinkSync(path.join(dir, lk)); } catch {}
    }
}

function downloadFile(url, dest) {
    return new Promise((resolve, reject) => {
        const mod = url.startsWith('https') ? https : http;
        const file = fs.createWriteStream(dest);
        mod.get(url, (res) => {
            if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
                // Follow redirect
                downloadFile(res.headers.location, dest).then(resolve).catch(reject);
                return;
            }
            res.pipe(file);
            file.on('finish', () => { file.close(); resolve(); });
        }).on('error', (e) => { fs.unlinkSync(dest); reject(e); });
    });
}

(async () => {
    if (!TARGET_URL) {
        log('Usage: node recaptcha_audio_solver.js <url> [profile_dir]');
        process.exit(1);
    }

    // Ensure profile
    if (!fs.existsSync(PROFILE)) {
        const src = '/home/ramza/credenciais_cadunico/google_profile_logged';
        if (fs.existsSync(src)) {
            const { execSync } = require('child_process');
            fs.mkdirSync(path.dirname(PROFILE), { recursive: true });
            execSync(`cp -a "${src}" "${PROFILE}"`, { timeout: 30000 });
            log('Profile cloned');
        }
    }
    cleanLocks(PROFILE);

    log('Launching stealth Chrome...');
    const browser = await puppeteer.launch({
        headless: process.platform === 'win32' ? 'new' : false,
        ...(CHROME ? {executablePath: CHROME} : {}),
        userDataDir: PROFILE,
        args: [
            '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
            '--window-size=1400,900', '--no-first-run', '--disable-extensions',
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
    await page.goto(TARGET_URL, { waitUntil: 'networkidle2', timeout: 30000 });
    log('Page loaded');

    // Post-navigation JS (e.g. submit form to reach captcha page)
    if (POST_NAV_JS) {
        log(`Running post-nav JS...`);
        try {
            await page.evaluate(POST_NAV_JS);
            await new Promise(r => setTimeout(r, 3000));
            // Wait for any navigation triggered by post-nav
            try { await page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 10000 }); } catch {}
            log('Post-nav done');
        } catch (e) {
            log('Post-nav error: ' + e.message);
        }
    }

    // Wait for reCAPTCHA iframe to appear
    await new Promise(r => setTimeout(r, 2000));

    // Find and click the reCAPTCHA checkbox
    // Support both standard reCAPTCHA v2 and Enterprise
    const recaptchaFrame = page.frames().find(f =>
        f.url().includes('recaptcha/api2/anchor') || f.url().includes('recaptcha/enterprise/anchor')
    );
    if (!recaptchaFrame) {
        log('No reCAPTCHA iframe found (checked api2 + enterprise)');
        respond({ status: 'error', error: 'no_recaptcha_iframe' });
        await browser.close();
        process.exit(1);
    }

    log('Found reCAPTCHA iframe, clicking checkbox...');
    try {
        await recaptchaFrame.waitForSelector('.recaptcha-checkbox-border', { timeout: 5000 });
        await recaptchaFrame.click('.recaptcha-checkbox-border');
    } catch (e) {
        log('Checkbox click failed: ' + e.message);
        respond({ status: 'error', error: 'checkbox_click_failed' });
        await browser.close();
        process.exit(1);
    }

    // Wait and check if auto-solved (high score = checkbox turns green without challenge)
    await new Promise(r => setTimeout(r, 3000));

    // Check for token (auto-solved)
    let token = await page.evaluate(() => {
        const ta = document.querySelector('textarea[name="g-recaptcha-response"]');
        return (ta && ta.value && ta.value.length > 20) ? ta.value : '';
    });

    if (token) {
        log(`Auto-solved! Token: ${token.length} chars`);
        respond({ status: 'auto_solved', token });
        await browser.close();
        process.exit(0);
    }

    // Challenge appeared - find the challenge iframe
    log('Challenge appeared, looking for audio button...');
    await new Promise(r => setTimeout(r, 1000));

    const challengeFrame = page.frames().find(f =>
        f.url().includes('recaptcha/api2/bframe') || f.url().includes('recaptcha/enterprise/bframe')
    );
    if (!challengeFrame) {
        log('No challenge iframe found');
        respond({ status: 'error', error: 'no_challenge_iframe' });
        await browser.close();
        process.exit(1);
    }

    // Click audio button
    try {
        await challengeFrame.waitForSelector('#recaptcha-audio-button', { timeout: 5000 });
        await challengeFrame.click('#recaptcha-audio-button');
        log('Clicked audio button');
    } catch (e) {
        log('Audio button not found: ' + e.message);
        respond({ status: 'error', error: 'no_audio_button' });
        await browser.close();
        process.exit(1);
    }

    await new Promise(r => setTimeout(r, 2000));

    // Check if blocked ("Your computer or network may be sending automated queries")
    try {
        const blocked = await challengeFrame.evaluate(() => {
            const el = document.querySelector('.rc-doscaptcha-header-text');
            return el ? el.textContent : '';
        });
        if (blocked && blocked.includes('automated')) {
            log('BLOCKED by Google: ' + blocked);
            respond({ status: 'challenge_blocked', error: blocked });
            await browser.close();
            process.exit(1);
        }
    } catch (e) {}

    // Get audio URL
    let audioUrl = '';
    try {
        audioUrl = await challengeFrame.evaluate(() => {
            const link = document.querySelector('.rc-audiochallenge-tdownload-link');
            return link ? link.href : '';
        });
    } catch (e) {}

    if (!audioUrl) {
        // Try alternative: audio source element
        try {
            audioUrl = await challengeFrame.evaluate(() => {
                const audio = document.querySelector('#audio-source');
                return audio ? audio.src : '';
            });
        } catch (e) {}
    }

    if (!audioUrl) {
        log('No audio URL found');
        respond({ status: 'error', error: 'no_audio_url' });
        await browser.close();
        process.exit(1);
    }

    log(`Audio URL: ${audioUrl.substring(0, 80)}...`);

    // Download audio
    const audioFile = `/tmp/recaptcha_audio_${Date.now()}.mp3`;
    try {
        await downloadFile(audioUrl, audioFile);
        log(`Audio downloaded: ${audioFile}`);
    } catch (e) {
        log('Audio download failed: ' + e.message);
        respond({ status: 'error', error: 'audio_download_failed' });
        await browser.close();
        process.exit(1);
    }

    // Send audio info to Python for Whisper transcription
    respond({ status: 'audio_challenge', audio_url: audioUrl, audio_file: audioFile });

    // Wait for answer from Python via stdin
    const rl = readline.createInterface({ input: process.stdin });
    const answerPromise = new Promise((resolve) => {
        rl.on('line', (line) => {
            try {
                const msg = JSON.parse(line.trim());
                if (msg.answer !== undefined) {
                    resolve(msg.answer);
                }
            } catch {}
        });
        // Timeout after 30s
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

    // Type the answer
    try {
        const inputField = await challengeFrame.$('#audio-response');
        if (inputField) {
            await inputField.click();
            await inputField.type(answer, { delay: 50 });
            log('Answer typed');
        }
    } catch (e) {
        log('Failed to type answer: ' + e.message);
    }

    // Click verify
    try {
        await challengeFrame.click('#recaptcha-verify-button');
        log('Clicked verify');
    } catch (e) {
        log('Verify click failed: ' + e.message);
    }

    // Wait for result
    await new Promise(r => setTimeout(r, 3000));

    // Check for token
    token = await page.evaluate(() => {
        const ta = document.querySelector('textarea[name="g-recaptcha-response"]');
        return (ta && ta.value && ta.value.length > 20) ? ta.value : '';
    });

    if (token) {
        log(`Solved! Token: ${token.length} chars`);
        respond({ status: 'solved', token });
    } else {
        // Check if new challenge appeared (wrong answer)
        log('No token after verify - answer may be wrong');
        respond({ status: 'failed', error: 'wrong_answer_or_new_challenge' });
    }

    // Clean up audio file
    try { fs.unlinkSync(audioFile); } catch {}

    await browser.close();
    process.exit(token ? 0 : 1);
})().catch(e => {
    log('Fatal: ' + e.message);
    respond({ status: 'error', error: e.message });
    process.exit(1);
});

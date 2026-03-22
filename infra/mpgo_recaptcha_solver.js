/**
 * MPGO reCAPTCHA Solver — Stealth auto-solve
 * 
 * The MPGO site has reCAPTCHA v2 that auto-solves with stealth browser.
 * Falls back to audio+Whisper if challenge appears.
 * 
 * Stdout: JSON with token or error
 * Stdin: audio answer (if challenge appears)
 * 
 * Usage: node mpgo_recaptcha_solver.js
 */
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const https = require('https');
const http = require('http');
const fs = require('fs');
const readline = require('readline');

puppeteer.use(StealthPlugin());

function log(msg) { process.stderr.write(`[MPGO-RC][${new Date().toTimeString().slice(0,8)}] ${msg}\n`); }
function respond(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }

function downloadFile(url, dest) {
    return new Promise((resolve, reject) => {
        const mod = url.startsWith('https') ? https : http;
        const file = fs.createWriteStream(dest);
        mod.get(url, (res) => {
            if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
                downloadFile(res.headers.location, dest).then(resolve).catch(reject);
                return;
            }
            res.pipe(file);
            file.on('finish', () => { file.close(); resolve(); });
        }).on('error', (e) => reject(e));
    });
}

(async () => {
    const browser = await puppeteer.launch({
        headless: false, executablePath: '/usr/bin/google-chrome',
        args: ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--window-size=1400,900',
               '--no-first-run','--disable-sync','--mute-audio',
               '--disable-infobars','--password-store=basic',
               '--disable-blink-features=AutomationControlled'],
        ignoreDefaultArgs: ['--enable-automation'],
        defaultViewport: null, ignoreHTTPSErrors: true,
    });

    const page = (await browser.pages())[0] || await browser.newPage();
    await page.setUserAgent('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36');

    log('Navigating to MPGO...');
    await page.goto('https://www.mpgo.mp.br/certidao', { waitUntil: 'networkidle2', timeout: 30000 });
    await new Promise(r => setTimeout(r, 4000));

    // Find reCAPTCHA frame
    const rcFrame = page.frames().find(f => f.url().includes('recaptcha/api2/anchor'));
    if (!rcFrame) {
        respond({ status: 'error', error: 'no_recaptcha' });
        await browser.close(); process.exit(1);
    }

    // Click via page mouse coords (more reliable than frame.click)
    const frameElement = await page.$('iframe[title*="reCAPTCHA"]');
    if (frameElement) {
        const box = await frameElement.boundingBox();
        if (box) {
            await page.mouse.click(box.x + 28, box.y + 28);
            log('Clicked checkbox');
        }
    } else {
        await rcFrame.click('.recaptcha-checkbox-border');
    }

    await new Promise(r => setTimeout(r, 4000));

    // Check auto-solve
    let token = await page.evaluate(() => {
        const ta = document.querySelector('textarea[name="g-recaptcha-response"]');
        return (ta && ta.value && ta.value.length > 20) ? ta.value : '';
    });

    if (token) {
        log(`Auto-solved! ${token.length} chars`);
        
        // Also get CSRF and cookies
        const csrf = await page.evaluate(() => {
            const m = document.querySelector('meta[name="csrf-token"]');
            return m ? m.content : '';
        });
        const cookies = await page.cookies();
        
        respond({ status: 'solved', token, csrf, cookies: cookies.map(c => `${c.name}=${c.value}`).join('; ') });
        await browser.close(); process.exit(0);
    }

    // Challenge appeared — try audio
    log('Challenge appeared, trying audio...');
    const chFrame = page.frames().find(f => f.url().includes('recaptcha/api2/bframe'));
    if (!chFrame) {
        respond({ status: 'error', error: 'no_challenge_frame' });
        await browser.close(); process.exit(1);
    }

    try {
        await chFrame.waitForSelector('#recaptcha-audio-button', { timeout: 5000 });
        await chFrame.click('#recaptcha-audio-button');
        log('Clicked audio button');
    } catch {
        respond({ status: 'error', error: 'no_audio_button' });
        await browser.close(); process.exit(1);
    }

    await new Promise(r => setTimeout(r, 3000));

    const audioSrc = await chFrame.evaluate(() => {
        const src = document.querySelector('#audio-source');
        return src ? src.src : '';
    });

    if (!audioSrc) {
        respond({ status: 'error', error: 'no_audio_source' });
        await browser.close(); process.exit(1);
    }

    const audioFile = `/tmp/mpgo_audio_${Date.now()}.mp3`;
    await downloadFile(audioSrc, audioFile);
    log(`Audio: ${audioFile}`);
    respond({ status: 'audio_challenge', audio_file: audioFile });

    // Wait for answer
    const rl = readline.createInterface({ input: process.stdin });
    const answer = await new Promise((resolve) => {
        const timer = setTimeout(() => resolve(''), 60000);
        rl.once('line', (line) => {
            clearTimeout(timer);
            try { resolve(JSON.parse(line).answer || ''); } catch { resolve(''); }
        });
    });
    rl.close();

    if (!answer) {
        respond({ status: 'failed', error: 'no_answer' });
        await browser.close(); process.exit(1);
    }

    const input = await chFrame.$('#audio-response');
    await input.click();
    await input.type(answer, { delay: 30 });
    await chFrame.click('#recaptcha-verify-button');
    log('Submitted answer');
    await new Promise(r => setTimeout(r, 5000));

    token = await page.evaluate(() => {
        const ta = document.querySelector('textarea[name="g-recaptcha-response"]');
        return (ta && ta.value && ta.value.length > 20) ? ta.value : '';
    });

    if (token) {
        const csrf = await page.evaluate(() => {
            const m = document.querySelector('meta[name="csrf-token"]');
            return m ? m.content : '';
        });
        const cookies = await page.cookies();
        respond({ status: 'solved', token, csrf, cookies: cookies.map(c => `${c.name}=${c.value}`).join('; ') });
        log(`Solved! ${token.length} chars`);
    } else {
        respond({ status: 'failed', error: 'no_token_after_audio' });
    }

    await browser.close();
})().catch(e => {
    log('Fatal: ' + e.message);
    respond({ status: 'error', error: e.message });
    process.exit(1);
});

/**
 * reCAPTCHA Enterprise Solver — Stealth auto-execute (invisible/score-based)
 * 
 * Para sites que usam grecaptcha.enterprise.execute() (sem checkbox visual).
 * Stealth browser consegue score alto o suficiente pra passar direto.
 * 
 * Protocolo stdout (JSON):
 *   → {"status":"solved","token":"..."}
 *   → {"status":"error","error":"..."}
 * 
 * Uso: DISPLAY=:121 NODE_PATH=/home/ramza/node_modules node recaptcha_enterprise_solver.js <url> <sitekey> [post_nav_js]
 */
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

const TARGET_URL = process.argv[2] || '';
const SITEKEY = process.argv[3] || '';
const POST_NAV_JS = process.argv[4] || '';
const ACTION = process.argv[5] || 'submit';
const CHROME = process.platform === 'win32' ? null : '/usr/bin/google-chrome';

function log(msg) { process.stderr.write(`[RCENT][${new Date().toTimeString().slice(0,8)}] ${msg}\n`); }
function respond(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }

(async () => {
    if (!TARGET_URL || !SITEKEY) {
        log('Usage: node recaptcha_enterprise_solver.js <url> <sitekey> [post_nav_js] [action]');
        process.exit(1);
    }

    log('Launching stealth Chrome...');
    const browser = await puppeteer.launch({
        headless: process.platform === 'win32' ? 'new' : false,
        ...(CHROME ? {executablePath: CHROME} : {}),
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

    // Post-navigation JS
    if (POST_NAV_JS) {
        log('Running post-nav JS...');
        try {
            await page.evaluate(POST_NAV_JS);
            await new Promise(r => setTimeout(r, 3000));
            try { await page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 10000 }); } catch {}
            log('Post-nav done');
        } catch (e) {
            log('Post-nav error: ' + e.message);
        }
    }

    // Wait for Enterprise JS to load
    await new Promise(r => setTimeout(r, 2000));

    // Check if grecaptcha.enterprise is available
    const hasEnterprise = await page.evaluate(() => {
        return typeof grecaptcha !== 'undefined' &&
               typeof grecaptcha.enterprise !== 'undefined' &&
               typeof grecaptcha.enterprise.execute === 'function';
    });

    if (!hasEnterprise) {
        // Wait more and retry
        log('Waiting for grecaptcha.enterprise to load...');
        await new Promise(r => setTimeout(r, 5000));
        const retry = await page.evaluate(() => {
            return typeof grecaptcha !== 'undefined' &&
                   typeof grecaptcha.enterprise !== 'undefined' &&
                   typeof grecaptcha.enterprise.execute === 'function';
        });
        if (!retry) {
            log('grecaptcha.enterprise not found');
            respond({ status: 'error', error: 'no_enterprise_api' });
            await browser.close();
            process.exit(1);
        }
    }

    log(`Executing enterprise.execute(${SITEKEY}, action=${ACTION})...`);
    try {
        const token = await page.evaluate(async (sk, act) => {
            return await grecaptcha.enterprise.execute(sk, { action: act });
        }, SITEKEY, ACTION);

        if (token && token.length > 20) {
            log(`Solved! Token: ${token.length} chars`);
            respond({ status: 'solved', token });
            await browser.close();
            process.exit(0);
        } else {
            log('Token empty or too short');
            respond({ status: 'error', error: 'token_empty' });
            await browser.close();
            process.exit(1);
        }
    } catch (e) {
        log('Execute failed: ' + e.message);
        respond({ status: 'error', error: e.message });
        await browser.close();
        process.exit(1);
    }
})().catch(e => {
    log('Fatal: ' + e.message);
    respond({ status: 'error', error: e.message });
    process.exit(1);
});

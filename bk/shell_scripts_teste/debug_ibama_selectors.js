/**
 * Debug: inspect reCAPTCHA Enterprise iframe selectors on IBAMA
 */
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

const PROFILE = '/home/ramza/telegram_downloads/PEDRO_PROJECT/infra/profiles/ibama_debug';
const fs = require('fs');
const path = require('path');

function cleanLocks(dir) {
    for (const lk of ['SingletonLock','SingletonCookie','SingletonSocket']) {
        try { fs.unlinkSync(path.join(dir, lk)); } catch {}
    }
}

(async () => {
    // Ensure profile
    if (!fs.existsSync(PROFILE)) {
        const { execSync } = require('child_process');
        fs.mkdirSync(path.dirname(PROFILE), { recursive: true });
        execSync(`cp -a "/home/ramza/credenciais_cadunico/google_profile_logged" "${PROFILE}"`, { timeout: 30000 });
    }
    cleanLocks(PROFILE);

    const browser = await puppeteer.launch({
        headless: false,
        executablePath: '/usr/bin/google-chrome',
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

    console.log('Navigating to IBAMA...');
    await page.goto('https://servicos.ibama.gov.br/sicafiext/sistema.php', { waitUntil: 'networkidle2', timeout: 30000 });
    console.log('Page loaded, running postNav...');

    // Navigate to certidão module
    await page.evaluate(() => {
        document.querySelector('input[name="modulo"]').value = 'sisarr/cons_emitir_certidao';
        document.forms['menuweb_submit'].submit();
    });
    await new Promise(r => setTimeout(r, 3000));
    try { await page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 10000 }); } catch {}
    console.log('PostNav done');

    // Wait for recaptcha to load
    await new Promise(r => setTimeout(r, 3000));

    // List all frames and their URLs
    const frames = page.frames();
    console.log(`\n=== FRAMES (${frames.length}) ===`);
    for (const f of frames) {
        console.log(`  URL: ${f.url()}`);
    }

    // Find anchor frame
    const anchorFrame = frames.find(f =>
        f.url().includes('recaptcha/enterprise/anchor') || f.url().includes('recaptcha/api2/anchor')
    );

    if (anchorFrame) {
        console.log(`\n=== ANCHOR FRAME: ${anchorFrame.url().substring(0, 100)} ===`);

        // Dump all elements inside
        const html = await anchorFrame.evaluate(() => document.documentElement.outerHTML);
        console.log(`\n=== ANCHOR IFRAME HTML (first 3000 chars) ===`);
        console.log(html.substring(0, 3000));

        // Check specific selectors
        const selectors = [
            '.recaptcha-checkbox-border',
            '.recaptcha-checkbox',
            '#recaptcha-anchor',
            '.rc-anchor-checkbox',
            '#rc-anchor-container',
            '[role="checkbox"]',
            '.rc-anchor',
        ];
        console.log('\n=== SELECTOR CHECK ===');
        for (const sel of selectors) {
            const found = await anchorFrame.evaluate((s) => {
                const el = document.querySelector(s);
                return el ? { tag: el.tagName, class: el.className, id: el.id, visible: el.offsetWidth > 0 } : null;
            }, sel);
            console.log(`  ${sel}: ${found ? JSON.stringify(found) : 'NOT FOUND'}`);
        }
    } else {
        console.log('\nNo anchor frame found!');
    }

    await browser.close();
    process.exit(0);
})().catch(e => {
    console.error('Fatal:', e.message);
    process.exit(1);
});

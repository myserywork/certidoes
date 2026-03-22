#!/usr/bin/env node
/**
 * Token Farm — Puppeteer-stealth persistent Chrome
 * 
 * Conceito: Chrome fica aberto na página CadUnico, gera tokens em loop
 * SEM reiniciar o browser. Quando IP queima, faz page.reload().
 * 
 * Saída: JSON por linha no stdout (igual protocol do worker v8)
 * Entrada: JSON por linha no stdin
 *   {"cmd":"gen"}     -> {"ok":true,"token":"..."}
 *   {"cmd":"reload"}  -> {"ok":true}
 *   {"cmd":"quit"}    -> {"ok":true,"produced":N}
 *   {"cmd":"batch","n":10} -> gera N tokens em sequência
 * 
 * Uso:
 *   sudo ip netns exec ns_t0 sudo -u ramza \
 *     DISPLAY=:99 node /home/ramza/token_farm.js --profile /home/ramza/credenciais_cadunico/profiles_v12/pup0
 */

const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

puppeteer.use(StealthPlugin());

const PAGE_URL = 'https://cadunico.dataprev.gov.br/#/consultaCpf';
const SITE_KEY = '6LfRVZIeAAAAAIwNb1YLXXL4T6W9-2tWRZ0Vufzk';

const JS_READY = "typeof grecaptcha!=='undefined'&&typeof grecaptcha.execute==='function'";
const JS_READ  = 'document.querySelector("textarea[name=g-recaptcha-response]")?.value||""';
const JS_EXEC  = 'grecaptcha.execute(0)';

// Parse args
const args = process.argv.slice(2);
let profileDir = '/home/ramza/credenciais_cadunico/profiles_v12/pup0';
let sourceProfile = '/home/ramza/credenciais_cadunico/google_profile_logged';
let chromePath = '/usr/bin/google-chrome';
let headless = false;

for (let i = 0; i < args.length; i++) {
    if (args[i] === '--profile' && args[i+1]) profileDir = args[++i];
    if (args[i] === '--source-profile' && args[i+1]) sourceProfile = args[++i];
    if (args[i] === '--chrome' && args[i+1]) chromePath = args[++i];
    if (args[i] === '--headless') headless = true;
}

function log(msg) {
    process.stderr.write(`[TF][${new Date().toTimeString().slice(0,8)}] ${msg}\n`);
}

function respond(data) {
    process.stdout.write(JSON.stringify(data) + '\n');
}

// Clone source profile if needed
function ensureProfile() {
    if (!fs.existsSync(profileDir) && fs.existsSync(sourceProfile)) {
        log(`Clonando profile de ${sourceProfile}`);
        const { execSync } = require('child_process');
        // Garantir que o diretório pai existe
        const parentDir = path.dirname(profileDir);
        if (!fs.existsSync(parentDir)) {
            fs.mkdirSync(parentDir, { recursive: true });
        }
        execSync(`cp -a "${sourceProfile}" "${profileDir}"`, { timeout: 30000 });
    }
    // Clean locks
    const locks = [
        'SingletonLock', 'SingletonCookie', 'SingletonSocket',
        'Default/LOCK', 'Default/Session Storage/LOCK',
        'Default/Local Storage/LOCK', 'Default/IndexedDB/LOCK'
    ];
    for (const lk of locks) {
        try { fs.unlinkSync(path.join(profileDir, lk)); } catch {}
    }
}

let browser = null;
let page = null;
let produced = 0;
let consecutiveFails = 0;
let reloadPromise = null;  // mutex para reload

async function waitRecaptcha(pg, timeout = 10000) {
    const start = Date.now();
    while (Date.now() - start < timeout) {
        try {
            const ready = await pg.evaluate(JS_READY);
            if (ready) return true;
        } catch {}
        await new Promise(r => setTimeout(r, 250));
    }
    return false;
}

async function readToken(pg) {
    try {
        const tk = await pg.evaluate(JS_READ);
        if (tk && tk.length > 50) return tk;
    } catch {}
    return '';
}

async function openBrowser() {
    ensureProfile();
    
    log('Abrindo Chrome com Puppeteer-stealth...');
    browser = await puppeteer.launch({
        headless: headless,
        executablePath: chromePath,
        userDataDir: profileDir,
        args: [
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-blink-features=AutomationControlled',
            '--disable-gpu',
            '--window-size=800,600',
            '--no-first-run',
            '--disable-default-apps',
            '--disable-extensions',
            '--disable-sync',
            '--disable-translate',
            '--metrics-recording-only',
            '--mute-audio',
            '--disable-features=IsolateOrigins,site-per-process',
            '--disable-infobars',
            '--disable-breakpad',
            '--password-store=basic',
        ],
        ignoreDefaultArgs: ['--enable-automation'],
        defaultViewport: null,
    });

    const pages = await browser.pages();
    page = pages[0] || await browser.newPage();
    
    // Navegar para a página do CadUnico
    log(`Navegando para ${PAGE_URL}`);
    try {
        await page.goto(PAGE_URL, { waitUntil: 'networkidle2', timeout: 30000 });
    } catch (e) {
        log(`Erro ao navegar: ${e.message}`);
        return false;
    }

    // Esperar reCAPTCHA ficar pronto
    const ready = await waitRecaptcha(page);
    if (!ready) {
        log('reCAPTCHA NÃO ficou pronto em 10s');
        return false;
    }

    log('reCAPTCHA pronto!');
    return true;
}

async function genToken() {
    if (!page) return '';
    
    // Esperar reload anterior terminar (se houver)
    if (reloadPromise) {
        try { await reloadPromise; } catch {}
        reloadPromise = null;
    }

    // Garantir reCAPTCHA pronto antes de tentar
    const ready = await waitRecaptcha(page, 8000);
    if (!ready) {
        log('reCAPTCHA não pronto, skip gen');
        consecutiveFails++;
        return '';
    }

    try {
        // Step 1: auto-token já disponível?
        let tk = await readToken(page);
        if (tk) {
            produced++;
            consecutiveFails = 0;
            log(`Auto-token harvested (${tk.length} chars)`);
            return tk;
        }

        // Step 2: executar reCAPTCHA (com timeout 10s)
        try {
            await Promise.race([
                page.evaluate(JS_EXEC),
                new Promise((_, rej) => setTimeout(() => rej(new Error('exec timeout')), 10000))
            ]);
        } catch (e) {
            log(`Execute error: ${e.message}`);
        }
        
        // Poll por 10 segundos
        for (let i = 0; i < 40; i++) {
            await new Promise(r => setTimeout(r, 250));
            tk = await readToken(page);
            if (tk) {
                produced++;
                consecutiveFails = 0;
                log(`Execute-token OK (${tk.length} chars)`);
                return tk;
            }
        }

        consecutiveFails++;
        log(`Token gen FAIL (consecutive: ${consecutiveFails})`);
    } catch (e) {
        consecutiveFails++;
        log(`Token gen error: ${e.message}`);
    }
    return '';
}

async function reloadPage() {
    if (!page) return false;
    try {
        log('Reloading page...');
        // Navegar para blank primeiro, depois voltar
        await page.goto('about:blank', { timeout: 5000 });
        await new Promise(r => setTimeout(r, 300));
        await page.goto(PAGE_URL, { waitUntil: 'networkidle2', timeout: 20000 });
        await new Promise(r => setTimeout(r, 1000));
        const ready = await waitRecaptcha(page);
        if (ready) {
            consecutiveFails = 0;
            log('Page reloaded, reCAPTCHA pronto');
            return true;
        }
        log('Page reloaded mas reCAPTCHA não ficou pronto');
        return false;
    } catch (e) {
        log(`Reload error: ${e.message}`);
        return false;
    }
}

async function closeBrowser() {
    if (browser) {
        try { await browser.close(); } catch {}
        browser = null;
        page = null;
    }
}

async function main() {
    const ok = await openBrowser();
    if (!ok) {
        respond({ ok: false, error: 'browser_open_failed' });
        // Tentar uma vez mais
        await closeBrowser();
        const ok2 = await openBrowser();
        if (!ok2) {
            respond({ ok: false, error: 'browser_open_failed_twice' });
            process.exit(1);
        }
    }
    
    respond({ ok: true, status: 'ready' });

    // Ler comandos do stdin
    const rl = readline.createInterface({ input: process.stdin });

    rl.on('line', async (line) => {
        let msg;
        try {
            msg = JSON.parse(line.trim());
        } catch {
            return;
        }

        const cmd = msg.cmd || '';

        if (cmd === 'gen') {
            const tk = await genToken();
            if (tk) {
                respond({ ok: true, token: tk });
                // NÃO fazer auto-reload — o caller Python faz reload explícito
            } else {
                respond({ ok: false, error: 'token_fail' });
                // Auto-reload se muitos fails consecutivos
                if (consecutiveFails >= 3) {
                    log('3 fails consecutivos, auto-reload...');
                    await reloadPage();
                }
            }
        }
        else if (cmd === 'reload') {
            const ok = await reloadPage();
            respond({ ok });
        }
        else if (cmd === 'batch') {
            // Gerar N tokens em sequência
            const n = msg.n || 5;
            const tokens = [];
            for (let i = 0; i < n; i++) {
                const tk = await genToken();
                if (tk) {
                    tokens.push(tk);
                } else {
                    // Se falhou, tentar reload e continuar
                    if (consecutiveFails >= 2) {
                        await reloadPage();
                    }
                }
            }
            respond({ ok: tokens.length > 0, tokens, count: tokens.length, total: n });
        }
        else if (cmd === 'quit') {
            respond({ ok: true, produced });
            rl.close();
            await closeBrowser();
            process.exit(0);
        }
        else {
            respond({ ok: false, error: `unknown cmd: ${cmd}` });
        }
    });

    rl.on('close', async () => {
        log('stdin closed, quitting');
        await closeBrowser();
        process.exit(0);
    });

    // Watchdog: se o browser crashar
    browser.on('disconnected', () => {
        log('Browser disconnected!');
        process.exit(1);
    });
}

main().catch(e => {
    log(`Fatal: ${e.message}`);
    process.exit(1);
});

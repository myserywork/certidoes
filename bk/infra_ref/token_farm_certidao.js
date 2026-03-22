#!/usr/bin/env node
/**
 * Token Farm — Certidões (adaptado do CadUnico token_farm.js)
 * 
 * Mesmo conceito: Chrome fica aberto na página do site-alvo,
 * Google profile logado = score alto = reCAPTCHA auto-passa.
 * 
 * Multi-site: TCU (reCAPTCHA v2), IBAMA (reCAPTCHA v2), CPF Receita (hCaptcha), MPF (Turnstile)
 * 
 * Para reCAPTCHA v2: com score alto, checkbox auto-passa SEM challenge visual.
 * Para hCaptcha: stealth browser + bom score = auto-solve.
 * Para Turnstile: stealth browser resolve automaticamente.
 * 
 * Saída: JSON por linha no stdout
 *   {"cmd":"gen"}           → {"ok":true,"token":"..."}
 *   {"cmd":"reload"}        → {"ok":true}
 *   {"cmd":"submit","data":{}} → preenche e submete formulário, retorna HTML resultado
 *   {"cmd":"quit"}          → {"ok":true,"produced":N}
 * 
 * Uso:
 *   DISPLAY=:120 node token_farm_certidao.js --site tcu --profile /path/to/profile
 *   DISPLAY=:120 node token_farm_certidao.js --site ibama
 *   DISPLAY=:120 node token_farm_certidao.js --site cpf_receita
 *   DISPLAY=:120 node token_farm_certidao.js --site mpf
 */

const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

puppeteer.use(StealthPlugin());

// ─── SITE CONFIGS ────────────────────────────────────────────────
const SITES = {
    tcu: {
        url: 'https://contas.tcu.gov.br/certidao/Web/Certidao/NadaConsta/home.faces',
        captchaType: 'recaptcha_v2',
        sitekey: '6LcRIUAkAAAAAGWdjhHC8mn-5A87StjjSVkn9N54',
        // Para v2: clicar checkbox, se score alto = auto-pass
        jsReady: "typeof grecaptcha!=='undefined'",
        jsToken: 'document.querySelector("textarea[name=g-recaptcha-response]")?.value||""',
        jsExec: 'grecaptcha.execute()',
        // Alternativa: clicar no checkbox iframe
        jsClickCheckbox: `
            (function(){
                var iframe = document.querySelector('iframe[src*="recaptcha"]');
                if(iframe) {
                    var rect = iframe.getBoundingClientRect();
                    return {x: rect.x + 30, y: rect.y + 30, found: true};
                }
                return {found: false};
            })()
        `,
    },
    ibama: {
        url: 'https://servicos.ibama.gov.br/sicafiext/sistema.php',
        captchaType: 'recaptcha_v2',
        sitekey: '6Ld2bNsrAAAAAML-kvSg-Yy3VwoXvxkr3Ymgq2t7',
        // Precisa navegar para o módulo primeiro
        postNav: async (page) => {
            // Submeter form para ir ao módulo de certidão
            await page.evaluate(`
                document.querySelector('input[name="modulo"]').value = 'sisarr/cons_emitir_certidao';
                document.forms['menuweb_submit'].submit();
            `);
            await page.waitForNavigation({waitUntil: 'networkidle2', timeout: 15000}).catch(()=>{});
        },
        jsReady: "typeof grecaptcha!=='undefined'",
        jsToken: 'document.querySelector("textarea[name=g-recaptcha-response]")?.value||""',
        jsExec: 'grecaptcha.execute()',
        jsClickCheckbox: `
            (function(){
                var iframe = document.querySelector('iframe[src*="recaptcha"]');
                if(iframe) {
                    var rect = iframe.getBoundingClientRect();
                    return {x: rect.x + 30, y: rect.y + 30, found: true};
                }
                return {found: false};
            })()
        `,
    },
    cpf_receita: {
        url: 'https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/consultapublica.asp',
        captchaType: 'hcaptcha',
        sitekey: '53be2ee7-5efc-494e-a3ba-c9258649c070',
        jsReady: "typeof hcaptcha!=='undefined'",
        jsToken: `
            (function(){
                // hCaptcha guarda token no textarea
                var ta = document.querySelector('textarea[name="h-captcha-response"]');
                if(ta && ta.value) return ta.value;
                var g = document.querySelector('textarea[name="g-recaptcha-response"]');
                if(g && g.value) return g.value;
                return '';
            })()
        `,
        jsExec: `
            (function(){
                if(typeof hcaptcha!=='undefined') {
                    try { hcaptcha.execute(); } catch(e) {}
                }
            })()
        `,
        jsClickCheckbox: `
            (function(){
                var iframe = document.querySelector('iframe[src*="hcaptcha"]');
                if(iframe) {
                    var rect = iframe.getBoundingClientRect();
                    return {x: rect.x + 30, y: rect.y + 30, found: true};
                }
                return {found: false};
            })()
        `,
    },
    mpf: {
        url: 'https://aplicativos.mpf.mp.br/ouvidoria/app/cidadao/certidao',
        captchaType: 'turnstile',
        sitekey: '0x4AAAAAACMhejJkLsBWVaMb',
        jsReady: "typeof turnstile!=='undefined'",
        jsToken: `
            (function(){
                // Turnstile guarda resposta no input hidden
                var inp = document.querySelector('input[name="cf-turnstile-response"]');
                if(inp && inp.value) return inp.value;
                // Também pode estar em variável Angular
                try {
                    var scope = angular.element(document.querySelector('[ng-controller]')).scope();
                    if(scope && scope.ctrl && scope.ctrl.recaptcha && scope.ctrl.recaptcha.response)
                        return scope.ctrl.recaptcha.response;
                } catch(e){}
                return '';
            })()
        `,
        jsExec: '', // Turnstile resolve sozinho
        jsClickCheckbox: `
            (function(){
                var iframe = document.querySelector('iframe[src*="turnstile"]');
                if(iframe) {
                    var rect = iframe.getBoundingClientRect();
                    return {x: rect.x + 30, y: rect.y + 30, found: true};
                }
                // Tentar div do widget
                var widget = document.querySelector('[turnstile-captcha]');
                if(widget) {
                    var rect = widget.getBoundingClientRect();
                    return {x: rect.x + 30, y: rect.y + 30, found: true};
                }
                return {found: false};
            })()
        `,
    },
};

// ─── ARGS ────────────────────────────────────────────────────────
const args = process.argv.slice(2);
let siteName = 'tcu';
let profileDir = '';
let sourceProfile = '/home/ramza/credenciais_cadunico/google_profile_logged';
let chromePath = '/usr/bin/google-chrome';
let headless = false;

for (let i = 0; i < args.length; i++) {
    if (args[i] === '--site' && args[i+1]) siteName = args[++i];
    if (args[i] === '--profile' && args[i+1]) profileDir = args[++i];
    if (args[i] === '--source-profile' && args[i+1]) sourceProfile = args[++i];
    if (args[i] === '--chrome' && args[i+1]) chromePath = args[++i];
    if (args[i] === '--headless') headless = true;
}

const site = SITES[siteName];
if (!site) {
    process.stderr.write(`Site desconhecido: ${siteName}. Disponíveis: ${Object.keys(SITES).join(', ')}\n`);
    process.exit(1);
}

if (!profileDir) {
    profileDir = `/home/ramza/telegram_downloads/PEDRO_PROJECT/infra/profiles/${siteName}`;
}

function log(msg) {
    process.stderr.write(`[TF-${siteName}][${new Date().toTimeString().slice(0,8)}] ${msg}\n`);
}

function respond(data) {
    process.stdout.write(JSON.stringify(data) + '\n');
}

// ─── Profile Management ─────────────────────────────────────────
function ensureProfile() {
    if (!fs.existsSync(profileDir) && fs.existsSync(sourceProfile)) {
        log(`Clonando profile de ${sourceProfile}`);
        const { execSync } = require('child_process');
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

// ─── Browser Functions ──────────────────────────────────────────
async function waitCaptchaReady(pg, timeout = 15000) {
    const start = Date.now();
    while (Date.now() - start < timeout) {
        try {
            const ready = await pg.evaluate(site.jsReady);
            if (ready) return true;
        } catch {}
        await new Promise(r => setTimeout(r, 300));
    }
    return false;
}

async function readToken(pg) {
    try {
        const tk = await pg.evaluate(site.jsToken);
        if (tk && tk.length > 20) return tk;
    } catch {}
    return '';
}

async function clickCheckbox(pg) {
    try {
        const pos = await pg.evaluate(site.jsClickCheckbox);
        if (pos && pos.found) {
            log(`Clicking captcha checkbox at (${pos.x}, ${pos.y})`);
            await pg.mouse.click(pos.x, pos.y);
            return true;
        }
    } catch (e) {
        log(`Click error: ${e.message}`);
    }
    return false;
}

async function openBrowser() {
    ensureProfile();
    
    log(`Abrindo Chrome stealth para ${siteName}...`);
    browser = await puppeteer.launch({
        headless: headless,
        executablePath: chromePath,
        userDataDir: profileDir,
        args: [
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-blink-features=AutomationControlled',
            '--disable-gpu',
            '--window-size=1280,900',
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
        ignoreHTTPSErrors: true,
    });

    const pages = await browser.pages();
    page = pages[0] || await browser.newPage();
    
    log(`Navegando para ${site.url}`);
    try {
        await page.goto(site.url, { waitUntil: 'networkidle2', timeout: 30000 });
    } catch (e) {
        log(`Erro ao navegar: ${e.message}`);
        return false;
    }

    // Post-navigation (ex: IBAMA precisa submeter form para chegar ao módulo)
    if (site.postNav) {
        try {
            await site.postNav(page);
            await new Promise(r => setTimeout(r, 2000));
        } catch (e) {
            log(`postNav error: ${e.message}`);
        }
    }

    // Esperar captcha ficar pronto
    await new Promise(r => setTimeout(r, 2000));
    const ready = await waitCaptchaReady(page);
    if (!ready) {
        log('Captcha NÃO ficou pronto em 15s (pode não ter carregado ainda)');
        // Não é fatal — pode tentar mesmo assim
    } else {
        log('Captcha pronto!');
    }

    return true;
}

async function genToken() {
    if (!page) return '';

    try {
        // Step 1: token já disponível? (auto-solved)
        let tk = await readToken(page);
        if (tk) {
            produced++;
            consecutiveFails = 0;
            log(`Auto-token harvested (${tk.length} chars)`);
            return tk;
        }

        // Step 2: clicar checkbox do captcha (reCAPTCHA v2 / hCaptcha)
        if (site.captchaType === 'recaptcha_v2' || site.captchaType === 'hcaptcha') {
            await clickCheckbox(page);
            // Esperar 3s após clicar
            await new Promise(r => setTimeout(r, 3000));
            tk = await readToken(page);
            if (tk) {
                produced++;
                consecutiveFails = 0;
                log(`Checkbox-token OK (${tk.length} chars)`);
                return tk;
            }
        }

        // Step 3: tentar execute() programático
        if (site.jsExec) {
            try {
                await Promise.race([
                    page.evaluate(site.jsExec),
                    new Promise((_, rej) => setTimeout(() => rej(new Error('exec timeout')), 10000))
                ]);
            } catch (e) {
                log(`Execute error: ${e.message}`);
            }
        }
        
        // Poll por 15 segundos
        for (let i = 0; i < 60; i++) {
            await new Promise(r => setTimeout(r, 250));
            tk = await readToken(page);
            if (tk) {
                produced++;
                consecutiveFails = 0;
                log(`Execute-token OK (${tk.length} chars)`);
                return tk;
            }
        }

        // Step 4: Para Turnstile, pode demorar mais — esperar mais 10s
        if (site.captchaType === 'turnstile') {
            for (let i = 0; i < 40; i++) {
                await new Promise(r => setTimeout(r, 250));
                tk = await readToken(page);
                if (tk) {
                    produced++;
                    consecutiveFails = 0;
                    log(`Turnstile-token OK (${tk.length} chars)`);
                    return tk;
                }
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

async function submitForm(data) {
    /**
     * Preenche formulário e submete. Retorna HTML do resultado.
     * data: {cpf, cnpj, data_nascimento, tipo_pessoa}
     */
    if (!page) return {ok: false, error: 'no_page'};

    try {
        const cpf_cnpj = data.cpf || data.cnpj || '';
        
        if (siteName === 'tcu') {
            const tipo = (data.cpf && data.cpf.length <= 14) ? 'cpf' : 'cnpj';
            await page.evaluate(`
                var radios = document.querySelectorAll('input[name="formEmitirCertidaoNadaConsta:tipoPesquisa"]');
                for(var r of radios) { if(r.value === '${tipo}') r.click(); }
            `);
            await new Promise(r => setTimeout(r, 500));
            await page.evaluate(`
                var inp = document.getElementById('formEmitirCertidaoNadaConsta:txtCpfOuCnpj');
                if(inp) {
                    inp.value = '${cpf_cnpj.replace(/\D/g, '')}';
                    inp.dispatchEvent(new Event('input',{bubbles:true}));
                    inp.dispatchEvent(new Event('change',{bubbles:true}));
                }
            `);
            await new Promise(r => setTimeout(r, 500));
            // Setar seCaptcha = true (como o callback faria)
            await page.evaluate(`
                var se = document.getElementById('formEmitirCertidaoNadaConsta:seCaptcha');
                if(se) se.value = 'true';
            `);
            // Clicar Emitir
            await page.evaluate(`
                var btn = document.getElementById('formEmitirCertidaoNadaConsta:btnEmitirCertidao');
                if(btn) { btn.disabled = false; btn.click(); }
            `);
            
        } else if (siteName === 'ibama') {
            await page.evaluate(`
                var inp = document.getElementById('p_num_cpf_cnpj');
                if(inp) { inp.value = '${cpf_cnpj}'; inp.dispatchEvent(new Event('change',{bubbles:true})); }
            `);
            await new Promise(r => setTimeout(r, 500));
            await page.evaluate(`
                document.getElementById('formDinAcao').value = 'Pesquisar';
                document.forms['formdin'].submit();
            `);
            
        } else if (siteName === 'cpf_receita') {
            await page.evaluate(`
                document.getElementsByName('txtCPF')[0].value = '${cpf_cnpj}';
                document.getElementsByName('txtDataNascimento')[0].value = '${data.data_nascimento || ''}';
                document.getElementById('idCheckedReCaptcha').value = 'true';
            `);
            await page.evaluate(`document.getElementById('id_submit').click();`);
            
        } else if (siteName === 'mpf') {
            // MPF é SPA Angular — melhor usar API REST diretamente
            // Mas se estiver no browser, interagir com o form
            const tipoPessoa = data.tipo_pessoa || 'F';
            await page.evaluate(`
                var scope = angular.element(document.querySelector('[ng-controller]')).scope();
                scope.ctrl.certidao.tipoPessoa = '${tipoPessoa}';
                scope.ctrl.certidao.cpf = '${cpf_cnpj}';
                scope.$apply();
            `);
            await new Promise(r => setTimeout(r, 1000));
            // Clicar Consultar
            await page.evaluate(`
                document.querySelector('button[ng-click*="consultaNome"]')?.click();
            `);
        }

        // Esperar navegação / AJAX
        await new Promise(r => setTimeout(r, 5000));
        
        // Capturar resultado
        const html = await page.evaluate('document.documentElement.outerHTML');
        const text = await page.evaluate('document.body.innerText');
        
        return {
            ok: true,
            html: html,
            text: text.substring(0, 3000),
            url: page.url(),
        };
        
    } catch(e) {
        log(`Submit error: ${e.message}`);
        return {ok: false, error: e.message};
    }
}

async function reloadPage() {
    if (!page) return false;
    try {
        log('Reloading page...');
        await page.goto('about:blank', { timeout: 5000 });
        await new Promise(r => setTimeout(r, 300));
        await page.goto(site.url, { waitUntil: 'networkidle2', timeout: 25000 });
        
        if (site.postNav) {
            await site.postNav(page);
            await new Promise(r => setTimeout(r, 2000));
        }
        
        await new Promise(r => setTimeout(r, 1500));
        const ready = await waitCaptchaReady(page);
        if (ready) {
            consecutiveFails = 0;
            log('Page reloaded, captcha pronto');
            return true;
        }
        log('Page reloaded mas captcha não ficou pronto');
        return false;
    } catch (e) {
        log(`Reload error: ${e.message}`);
        return false;
    }
}

async function getPageInfo() {
    if (!page) return {ok: false};
    try {
        const url = page.url();
        const title = await page.title();
        const text = await page.evaluate('document.body.innerText.substring(0,500)');
        return {ok: true, url, title, text};
    } catch(e) {
        return {ok: false, error: e.message};
    }
}

async function closeBrowser() {
    if (browser) {
        try { await browser.close(); } catch {}
        browser = null;
        page = null;
    }
}

// ─── MAIN ────────────────────────────────────────────────────────
async function main() {
    const ok = await openBrowser();
    if (!ok) {
        respond({ ok: false, error: 'browser_open_failed' });
        await closeBrowser();
        const ok2 = await openBrowser();
        if (!ok2) {
            respond({ ok: false, error: 'browser_open_failed_twice' });
            process.exit(1);
        }
    }
    
    respond({ ok: true, status: 'ready', site: siteName });

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
            } else {
                respond({ ok: false, error: 'token_fail' });
                if (consecutiveFails >= 3) {
                    log('3 fails, auto-reload...');
                    await reloadPage();
                }
            }
        }
        else if (cmd === 'submit') {
            const result = await submitForm(msg.data || {});
            respond(result);
        }
        else if (cmd === 'reload') {
            const ok = await reloadPage();
            respond({ ok });
        }
        else if (cmd === 'info') {
            const info = await getPageInfo();
            respond(info);
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

    browser.on('disconnected', () => {
        log('Browser disconnected!');
        process.exit(1);
    });
}

main().catch(e => {
    log(`Fatal: ${e.message}`);
    process.exit(1);
});

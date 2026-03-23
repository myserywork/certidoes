/**
 * STF Certidão Solver — Full Pipeline
 * 
 * 1. Solve AWS WAF (audio + Whisper via stdin/stdout)
 * 2. Execute grecaptcha.enterprise.execute() for reCAPTCHA token
 * 3. POST to /api/certidao/distribuicao (or other type)
 * 4. Download PDF from emissor URL
 * 5. Return result
 * 
 * Protocol (JSON lines stdout/stdin):
 *   → {"status":"audio_challenge","audio_file":"/tmp/..."}
 *   ← {"answer":"word"}
 *   → {"status":"waf_solved"}
 *   → {"status":"certidao_result","data":{...},"pdf_path":"/tmp/..."}
 *   → {"status":"error","error":"..."}
 * 
 * Usage: node stf_certidao_solver.js <cpf_or_cnpj> [tipo] [nome] [extra_json]
 *   tipo: distribuicao (default), antecedentes-criminais, fins-eleitorais, atuacao-de-advogado
 *   extra_json: JSON with additional form fields
 */
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');
const path = require('path');
const readline = require('readline');
puppeteer.use(StealthPlugin());

const CHROME = process.platform === 'win32' ? null : '/usr/bin/google-chrome';
const TARGET = 'https://certidoes.stf.jus.br';
const EMISSOR = 'https://certidoes-api.stf.jus.br/certidoes';
const SITEKEY = '6Lc6IFQsAAAAANA-LwhawfStAlHLQtiB4RwT0jex';

const DOC = process.argv[2] || '';
const TIPO = process.argv[3] || 'distribuicao';
const NOME = process.argv[4] || '';
const EXTRA_JSON = process.argv[5] || '{}';

function log(msg) { process.stderr.write(`[STF-SOLVER][${new Date().toTimeString().slice(0,8)}] ${msg}\n`); }
function respond(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }

function waitStdin() {
    return new Promise(resolve => {
        const rl = readline.createInterface({input: process.stdin});
        rl.on('line', line => {
            try { const m = JSON.parse(line.trim()); if (m.answer !== undefined) { rl.close(); resolve(m.answer); } } catch {}
        });
        setTimeout(() => { rl.close(); resolve(''); }, 45000);
    });
}

function isCPF(doc) { return doc.replace(/\D/g, '').length === 11; }
function isCNPJ(doc) { return doc.replace(/\D/g, '').length === 14; }
function cleanDoc(doc) { return doc.replace(/\D/g, ''); }

async function solveWAF(page, maxRetries = 3) {
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
        const hasGoku = await page.evaluate(() => typeof window.gokuProps !== 'undefined');
        if (!hasGoku) {
            log('No WAF');
            return true;
        }
        
        log(`WAF attempt ${attempt}/${maxRetries}...`);
        await new Promise(r => setTimeout(r, 2000));
        
        // Click Begin
        await page.evaluate(() => {
            document.querySelectorAll('button').forEach(b => {
                if (b.textContent.trim() === 'Begin') b.click();
            });
        });
        await new Promise(r => setTimeout(r, 3000));
        
        // Click audio
        await page.evaluate(() => {
            document.querySelectorAll('button').forEach(b => {
                const img = b.querySelector('img');
                if (img && img.alt && img.alt.includes('audio')) b.click();
            });
        });
        await new Promise(r => setTimeout(r, 3000));
        
        // Click Play Audio
        await page.evaluate(() => {
            document.querySelectorAll('button').forEach(b => {
                if (b.textContent.includes('Play')) b.click();
            });
        });
        await new Promise(r => setTimeout(r, 4000));
        
        // Extract audio — wait for src to be populated (may change after Play)
        let audioData = null;
        for (let wait = 0; wait < 5; wait++) {
            audioData = await page.evaluate(() => {
                const a = document.querySelector('audio');
                if (!a) return null;
                const src = a.src || '';
                const source = a.querySelector('source');
                const srcEl = source ? source.src : '';
                const result = src || srcEl || null;
                // Must be a data URL (base64) or http URL, not empty
                return (result && result.length > 100) ? result : null;
            });
            if (audioData) break;
            await new Promise(r => setTimeout(r, 1000));
        }
        
        if (!audioData || !audioData.startsWith('data:audio/')) {
            log('No audio data');
            if (attempt < maxRetries) { await page.reload({waitUntil: 'networkidle2'}); continue; }
            return false;
        }
        
        const match = audioData.match(/^data:audio\/([^;]+);base64,(.+)$/);
        if (!match) continue;
        
        const ext = match[1] === 'aac' ? 'aac' : match[1];
        const filePath = `/tmp/stf_waf_audio_${Date.now()}.${ext}`;
        fs.writeFileSync(filePath, Buffer.from(match[2], 'base64'));
        log(`Audio: ${filePath} (${Buffer.from(match[2], 'base64').length} bytes)`);
        
        respond({status: 'audio_challenge', audio_file: filePath});
        const answer = await waitStdin();
        
        if (!answer) {
            log('No Whisper answer');
            if (attempt < maxRetries) { await page.reload({waitUntil: 'networkidle2'}); continue; }
            return false;
        }
        
        log(`Answer: "${answer}"`);
        const input = await page.$('input[type="text"]');
        if (input) { await input.click({clickCount:3}); await input.type(answer, {delay:50}); }
        
        await page.evaluate(() => {
            document.querySelectorAll('button').forEach(b => {
                if (b.textContent.trim() === 'Confirm') b.click();
            });
        });
        
        await new Promise(r => setTimeout(r, 5000));
        try { await page.waitForNavigation({waitUntil:'networkidle2', timeout:10000}); } catch {}
        
        const stillWaf = await page.evaluate(() => typeof window.gokuProps !== 'undefined');
        if (!stillWaf) {
            log('WAF SOLVED!');
            return true;
        }
        
        log('Answer was wrong, retrying...');
        await page.reload({waitUntil: 'networkidle2'});
    }
    return false;
}

async function getRecaptchaToken(page, action) {
    log(`Getting reCAPTCHA Enterprise token (action: ${action})...`);
    
    // Wait for recaptcha to be ready
    for (let i = 0; i < 15; i++) {
        const ready = await page.evaluate(() => typeof grecaptcha !== 'undefined' && typeof grecaptcha.enterprise !== 'undefined');
        if (ready) break;
        await new Promise(r => setTimeout(r, 1000));
    }
    
    const token = await page.evaluate(async (sitekey, action) => {
        return new Promise((resolve, reject) => {
            if (typeof grecaptcha === 'undefined' || typeof grecaptcha.enterprise === 'undefined') {
                reject('grecaptcha.enterprise not available');
                return;
            }
            grecaptcha.enterprise.ready(async () => {
                try {
                    const token = await grecaptcha.enterprise.execute(sitekey, {action});
                    resolve(token);
                } catch (e) {
                    reject(e.message || e);
                }
            });
        });
    }, SITEKEY, action);
    
    log(`Token: ${token ? token.substring(0,50) + '...' : 'FAILED'} (${token ? token.length : 0} chars)`);
    return token;
}

function formatCPF(d) {
    d = d.replace(/\D/g, '').padStart(11, '0');
    return `${d.slice(0,3)}.${d.slice(3,6)}.${d.slice(6,9)}-${d.slice(9,11)}`;
}
function formatCNPJ(d) {
    d = d.replace(/\D/g, '').padStart(14, '0');
    return `${d.slice(0,2)}.${d.slice(2,5)}.${d.slice(5,8)}/${d.slice(8,12)}-${d.slice(12,14)}`;
}

// Map tipo CLI arg to API modelo field
const TIPO_TO_MODELO = {
    'distribuicao': 'DISTRIBUICAO',
    'antecedentes-criminais': 'ANTECEDENTES_CRIMINAIS',
    'fins-eleitorais': 'ANTECEDENTES_PARA_FINS_ELEITORAIS',
    'atuacao-de-advogado': 'ATUACAO_DE_ADVOGADO',
    'objeto-e-pe': 'OBJETO_E_PE',
};

function buildFormData(doc, tipo, nome, extraJson) {
    const digits = cleanDoc(doc);
    const isPF = isCPF(doc);
    let extra = {};
    try { extra = JSON.parse(extraJson); } catch {}
    
    // Valid CPF for solicitante (placeholder with valid check digits)
    const DEFAULT_CPF_SOLICITANTE = '529.982.247-25';
    const solicitanteCPF = extra.cpfDoSolicitante 
        ? formatCPF(extra.cpfDoSolicitante)
        : (isPF ? formatCPF(digits) : DEFAULT_CPF_SOLICITANTE);
    
    const base = {
        modelo: TIPO_TO_MODELO[tipo] || 'DISTRIBUICAO',
        tipoDePessoa: isPF ? 'FISICA' : 'JURIDICA',
        nome: nome || extra.nome || '',
        deAcordo: true,
        meioDeRecebimento: extra.meioDeRecebimento || 'EMAIL',
        emailDoSolicitante: extra.emailDoSolicitante || extra.email || 'certidao@solicitante.com.br',
        nomeDoSolicitante: extra.nomeDoSolicitante || (nome ? nome.substring(0, 40) : 'Solicitante da Certidao'),
        cpfDoSolicitante: solicitanteCPF,
        telefoneDoSolicitante: extra.telefoneDoSolicitante || extra.telefone || '(61) 9 8765-4321',
    };
    
    if (isPF) {
        base.cpf = formatCPF(digits);
        base.dataDeNascimento = extra.dataDeNascimento || extra.nascimento || '';
        base.rg = extra.rg ? String(extra.rg) : '';
        base.orgaoExpedidor = extra.orgaoExpedidor || '';
        base.estadoCivil = extra.estadoCivil || '';
        base.nomeDaMae = extra.nomeDaMae || '';
        base.nomeDoPai = extra.nomeDoPai || '';
        base.nacionalidade = extra.nacionalidade || 'BRASILEIRA';
        base.naturalidade = extra.naturalidade || '';
        base.uf = extra.uf || '';
    } else {
        base.cnpj = formatCNPJ(digits);
    }
    
    return {...base, ...extra};
}

(async () => {
    if (!DOC) {
        log('Usage: node stf_certidao_solver.js <cpf_or_cnpj> [tipo] [nome] [extra_json]');
        process.exit(1);
    }
    
    log(`Doc: ${DOC}, Tipo: ${TIPO}, Nome: ${NOME || '(auto)'}`);
    
    const browser = await puppeteer.launch({
        headless: process.platform === 'win32' ? 'new' : false, ...(CHROME ? {executablePath: CHROME} : {}),
        args: ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--window-size=1400,900',
               '--no-first-run','--disable-extensions','--disable-sync','--mute-audio',
               '--disable-infobars','--password-store=basic','--disable-blink-features=AutomationControlled'],
        ignoreDefaultArgs: ['--enable-automation'],
        defaultViewport: null, ignoreHTTPSErrors: true,
    });
    
    const page = (await browser.pages())[0];
    
    log(`Navigating to ${TARGET}`);
    await page.goto(TARGET, {waitUntil: 'networkidle2', timeout: 30000});
    
    // 1. Solve WAF
    if (!await solveWAF(page, 3)) {
        respond({status: 'error', error: 'WAF solve failed after 3 attempts'});
        await browser.close();
        process.exit(1);
    }
    respond({status: 'waf_solved'});
    
    // 2. Wait for reCAPTCHA Enterprise to load
    await new Promise(r => setTimeout(r, 3000));
    
    // 3. Get reCAPTCHA token
    const action = `pedido_certidao_${TIPO.replace(/-/g, '_')}`;
    const token = await getRecaptchaToken(page, action);
    
    if (!token) {
        respond({status: 'error', error: 'reCAPTCHA token failed'});
        await browser.close();
        process.exit(1);
    }
    
    // 4. Build form data
    const formData = buildFormData(DOC, TIPO, NOME, EXTRA_JSON);
    log(`Form data: ${JSON.stringify(formData).substring(0, 200)}`);
    
    // 5. POST to API (from within browser context — uses same cookies)
    const apiResult = await page.evaluate(async (tipo, formData, token) => {
        try {
            const resp = await fetch(`/api/certidao/${tipo}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-TOKEN-CAPTCHA': token,
                },
                body: JSON.stringify(formData),
            });
            
            const contentType = resp.headers.get('content-type') || '';
            
            if (contentType.includes('json')) {
                const data = await resp.json();
                return {ok: resp.ok, status: resp.status, data, isJson: true};
            } else {
                const text = await resp.text();
                return {ok: resp.ok, status: resp.status, text: text.substring(0, 5000), isJson: false};
            }
        } catch (e) {
            return {ok: false, error: e.message};
        }
    }, TIPO, formData, token);
    
    log(`API result: ${JSON.stringify(apiResult).substring(0, 500)}`);
    
    if (!apiResult.ok) {
        respond({status: 'api_error', data: apiResult});
        // Even on error, try to get useful info
    }
    
    // 6. If certidao was generated online, download PDF
    let pdfPath = null;
    const data = apiResult.data || {};
    
    if (data.geradaOnline) {
        const docClean = cleanDoc(DOC);
        const sujeitoNome = data.sujeitoDaCertidao || NOME || formData.nome;
        
        let pdfUrl = '';
        if (TIPO === 'distribuicao') {
            pdfUrl = `${EMISSOR}/api/negativa/distribuicao/gerar?nome=${encodeURIComponent(sujeitoNome)}&documento=${docClean}`;
        } else if (TIPO === 'antecedentes-criminais') {
            pdfUrl = `${EMISSOR}/api/negativa/antecedentes-criminais/gerar?nome=${encodeURIComponent(sujeitoNome)}&documento=${docClean}`;
        } else if (TIPO === 'fins-eleitorais') {
            pdfUrl = `${EMISSOR}/api/negativa/eleitoral/gerar/${encodeURIComponent(sujeitoNome)}/${docClean}`;
        } else if (TIPO === 'atuacao-de-advogado') {
            pdfUrl = `${EMISSOR}/api/negativa/atuacao-de-advogado/gerar?nome=${encodeURIComponent(sujeitoNome)}&documento=${docClean}`;
        }
        
        if (pdfUrl) {
            log(`Downloading PDF from: ${pdfUrl}`);
            
            // Download PDF from within browser (WAF cookies)
            const pdfData = await page.evaluate(async (url) => {
                try {
                    const resp = await fetch(url);
                    if (!resp.ok) return {error: `HTTP ${resp.status}`, text: await resp.text().catch(()=>'')};
                    const blob = await resp.blob();
                    const reader = new FileReader();
                    return new Promise((resolve) => {
                        reader.onloadend = () => resolve({base64: reader.result.split(',')[1], size: blob.size, type: blob.type});
                        reader.readAsDataURL(blob);
                    });
                } catch (e) {
                    return {error: e.message};
                }
            }, pdfUrl);
            
            if (pdfData.base64) {
                pdfPath = `/tmp/certidao_stf_${cleanDoc(DOC)}.pdf`;
                fs.writeFileSync(pdfPath, Buffer.from(pdfData.base64, 'base64'));
                log(`PDF saved: ${pdfPath} (${pdfData.size} bytes)`);
            } else {
                log(`PDF download failed: ${JSON.stringify(pdfData)}`);
            }
        }
    }
    
    // 7. If we got a protocolo, save it
    const protocolo = data.protocolo || data.id || null;
    if (protocolo) {
        log(`Protocolo: ${protocolo}`);
    }
    
    respond({
        status: apiResult.ok ? 'certidao_result' : 'api_error',
        data: apiResult.data || apiResult,
        pdf_path: pdfPath,
        protocolo,
    });
    
    await browser.close();
})().catch(e => {
    log('Fatal: ' + e.message);
    respond({status: 'error', error: e.message});
    process.exit(1);
});

/**
 * TST CNDT Captcha Solver — Extract audio captcha for Whisper
 * 
 * The TST CNDT uses a custom captcha:
 *   - Audio WAV base64 inline (letters/numbers dictated in Portuguese)
 *   - Image PNG base64 inline (visual captcha)
 *   - Response field: idCampoResposta
 *   - Token: tokenDesafio
 * 
 * Fluxo:
 *   1. Navigate to TST, click "Emitir Certidão"
 *   2. Extract audio base64, save to file
 *   3. Send audio path to Python (Whisper)
 *   4. Receive answer, type it, submit form
 *   5. Return result (certidão HTML or error)
 * 
 * Protocolo stdout (JSON por linha):
 *   → {"status":"page_loaded","has_captcha":true}
 *   → {"status":"audio","path":"/tmp/tst_audio.wav","token":"..."}
 *   ← {"answer":"YW3BFV"}
 *   → {"status":"submitted","html":"...(base64)...","url":"..."} | {"status":"failed","error":"..."}
 * 
 * Uso: DISPLAY=:121 NODE_PATH=/home/ramza/node_modules node tst_captcha_solver.js <cpf_cnpj>
 */
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');
const readline = require('readline');

puppeteer.use(StealthPlugin());

const CPF_CNPJ = process.argv[2] || '';
const TST_URL = 'https://cndt-certidao.tst.jus.br/inicio.faces';
const CHROME = process.platform === 'win32' ? null : '/usr/bin/google-chrome';
const MAX_ATTEMPTS = 3;

function log(msg) { process.stderr.write(`[TSTJS][${new Date().toTimeString().slice(0,8)}] ${msg}\n`); }
function respond(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }

function waitForLine(rl, timeoutMs = 60000) {
    return new Promise((resolve) => {
        const timer = setTimeout(() => resolve(null), timeoutMs);
        rl.once('line', (line) => {
            clearTimeout(timer);
            try { resolve(JSON.parse(line.trim())); } catch { resolve(null); }
        });
    });
}

(async () => {
    if (!CPF_CNPJ) {
        log('No CPF/CNPJ provided');
        process.exit(1);
    }

    const browser = await puppeteer.launch({
        headless: process.platform === 'win32' ? 'new' : false, ...(CHROME ? {executablePath: CHROME} : {}),
        args: ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--window-size=1200,900',
               '--no-first-run','--disable-extensions','--disable-sync','--mute-audio',
               '--disable-infobars','--password-store=basic',
               '--disable-blink-features=AutomationControlled'],
        ignoreDefaultArgs: ['--enable-automation'],
        defaultViewport: null, ignoreHTTPSErrors: true,
    });

    const page = (await browser.pages())[0] || await browser.newPage();
    const rl = readline.createInterface({ input: process.stdin });

    log(`Navigating to TST CNDT...`);
    await page.goto(TST_URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await new Promise(r => setTimeout(r, 2000));

    // Click "Emitir Certidão"
    log('Clicking Emitir Certidão...');
    await page.evaluate(() => {
        const btn = document.querySelector('input[value="Emitir Certidão"]');
        if (btn) btn.click();
    });
    await new Promise(r => setTimeout(r, 4000));

    // Check if captcha form loaded
    const hasCaptcha = await page.evaluate(() => {
        return !!document.querySelector('#idCampoResposta') || !!document.querySelector('#idAudioCaptcha');
    });

    if (!hasCaptcha) {
        log('No captcha form found!');
        respond({ status: 'error', error: 'no_captcha_form' });
        await browser.close();
        process.exit(1);
    }

    log('Captcha form found');

    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
        log(`--- Attempt ${attempt}/${MAX_ATTEMPTS} ---`);

        // Extract audio base64
        const audioData = await page.evaluate(() => {
            const audio = document.querySelector('#idAudioCaptcha');
            if (!audio || !audio.src) return null;
            const src = audio.src;
            if (!src.startsWith('data:audio')) return null;
            // Extract base64 part
            const b64 = src.split('base64,')[1];
            return b64 || null;
        });

        if (!audioData) {
            log('No audio data found');
            respond({ status: 'error', error: 'no_audio_data' });
            break;
        }

        // Save audio to file
        const audioPath = `/tmp/tst_audio_${Date.now()}.wav`;
        const audioBuffer = Buffer.from(audioData, 'base64');
        fs.writeFileSync(audioPath, audioBuffer);
        log(`Audio saved: ${audioPath} (${audioBuffer.length} bytes)`);

        // Get token
        const token = await page.evaluate(() => {
            const el = document.querySelector('#tokenDesafio');
            return el ? el.value : '';
        });

        // Send audio path to Python
        respond({ status: 'audio', path: audioPath, token, attempt });

        // Wait for Python answer
        const msg = await waitForLine(rl, 60000);
        if (!msg || !msg.answer) {
            log('No answer from Whisper');
            continue;
        }

        log(`Answer: "${msg.answer}"`);

        // Fill CPF/CNPJ field
        await page.evaluate((cpf) => {
            const field = document.querySelector('#gerarCertidaoForm\\:cpfCnpj, input[name="gerarCertidaoForm:cpfCnpj"]');
            if (field) {
                field.value = '';
                field.focus();
            }
        }, CPF_CNPJ);
        await page.type('input[name="gerarCertidaoForm:cpfCnpj"]', CPF_CNPJ, { delay: 30 });
        await new Promise(r => setTimeout(r, 300));

        // Fill captcha response
        await page.evaluate(() => {
            const field = document.querySelector('#idCampoResposta');
            if (field) { field.value = ''; field.focus(); }
        });
        await page.type('#idCampoResposta', msg.answer, { delay: 30 });
        await new Promise(r => setTimeout(r, 300));

        log(`Filled CPF: ${CPF_CNPJ}, Answer: ${msg.answer}`);

        // Click "Emitir Certidão" submit button
        log('Clicking submit...');
        await page.evaluate(() => {
            const btn = document.querySelector('#gerarCertidaoForm\\:btnEmitirCertidao');
            if (btn) btn.click();
        });
        await new Promise(r => setTimeout(r, 6000));

        // Check result
        const result = await page.evaluate(() => {
            const body = document.body.innerHTML;
            const url = window.location.href;
            
            // Check for error messages
            const errEl = document.querySelector('#mensagens, .mensagemErro, .erro');
            const errText = errEl ? errEl.textContent.trim() : '';
            
            // Check for certidão content
            const hasCertidao = body.includes('CERTID') || body.includes('Certid') || 
                               body.includes('CNDT') || body.includes('Débitos Trabalhistas');
            
            // Check if captcha was wrong (still on same page with captcha)
            const stillCaptcha = !!document.querySelector('#idCampoResposta');
            
            // Check for PDF/download link
            const pdfLink = document.querySelector('a[href*=".pdf"], a[href*="download"], iframe[src*=".pdf"]');
            const pdfUrl = pdfLink ? (pdfLink.href || pdfLink.src) : '';
            
            // Check for "podeFazerDownload"
            const canDownload = document.querySelector('#gerarCertidaoForm\\:podeFazerDownload');
            const downloadVal = canDownload ? canDownload.value : '';
            
            return {
                url,
                errText: errText.substring(0, 500),
                hasCertidao,
                stillCaptcha,
                pdfUrl,
                canDownload: downloadVal,
                htmlSize: body.length,
                title: document.title,
            };
        });

        log(`Result: url=${result.url}, err="${result.errText}", certidao=${result.hasCertidao}, stillCaptcha=${result.stillCaptcha}, canDownload=${result.canDownload}`);

        if (result.stillCaptcha && result.errText) {
            log(`Captcha wrong or error: ${result.errText}`);
            // Try to reload captcha for next attempt
            const hasNewAudio = await page.evaluate(() => !!document.querySelector('#idAudioCaptcha'));
            if (hasNewAudio) {
                log('New captcha loaded, retrying...');
                continue;
            }
        }

        if (result.hasCertidao || result.canDownload === 'true' || !result.stillCaptcha) {
            // Success! Get full HTML
            const fullHtml = await page.content();
            const b64Html = Buffer.from(fullHtml).toString('base64');
            respond({
                status: 'success',
                html_b64: b64Html,
                url: result.url,
                pdf_url: result.pdfUrl,
                can_download: result.canDownload,
                title: result.title,
            });
            log('Success!');
            break;
        }

        if (attempt >= MAX_ATTEMPTS) {
            respond({ status: 'failed', error: `max_attempts_exceeded`, last_error: result.errText });
        }
    }

    // Cleanup
    rl.close();
    await browser.close();
    process.exit(0);
})().catch(e => {
    log('Fatal: ' + e.message);
    respond({ status: 'error', error: e.message });
    process.exit(1);
});

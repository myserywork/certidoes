/**
 * STF Full Solver — Resolve WAF + Navigate SPA + Emit Certidão
 * 
 * Protocol (JSON lines on stdout, reads stdin):
 *   → {"status":"no_captcha"}
 *   → {"status":"audio_challenge","audio_file":"/tmp/..."}
 *   ← {"answer":"word"}
 *   → {"status":"waf_solved"}
 *   → {"status":"spa_mapped","data":{...}}
 *   → {"status":"certidao_emitida","pdf_base64":"...","html":"..."}
 *   → {"status":"error","error":"..."}
 */
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');
const readline = require('readline');
puppeteer.use(StealthPlugin());

const CHROME = '/usr/bin/google-chrome';
const TARGET = 'https://certidoes.stf.jus.br';
const CPF_CNPJ = process.argv[2] || '';
const MODE = process.argv[3] || 'explore'; // 'explore' or 'emit'

function log(msg) { process.stderr.write(`[STF-FULL][${new Date().toTimeString().slice(0,8)}] ${msg}\n`); }
function respond(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }

function waitForAnswer() {
    return new Promise(resolve => {
        const rl = readline.createInterface({input: process.stdin});
        rl.on('line', line => {
            try {
                const m = JSON.parse(line.trim());
                if (m.answer !== undefined) { rl.close(); resolve(m.answer); }
            } catch {}
        });
        setTimeout(() => { rl.close(); resolve(''); }, 45000);
    });
}

async function solveWAF(page) {
    const hasGoku = await page.evaluate(() => typeof window.gokuProps !== 'undefined');
    if (!hasGoku) {
        log('No WAF detected');
        respond({status: 'no_captcha'});
        return true;
    }
    
    log('WAF detected, solving...');
    await new Promise(r => setTimeout(r, 2000));
    
    // Click Begin
    await page.evaluate(() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) { if (b.textContent.trim() === 'Begin') { b.click(); return; } }
    });
    await new Promise(r => setTimeout(r, 3000));
    
    // Click audio button
    const audioClicked = await page.evaluate(() => {
        const btns = document.querySelectorAll('button.btn-icon, button');
        for (const b of btns) {
            const img = b.querySelector('img');
            if (img && img.alt && img.alt.includes('audio')) { b.click(); return true; }
        }
        return false;
    });
    if (!audioClicked) { log('No audio button'); return false; }
    await new Promise(r => setTimeout(r, 3000));
    
    // Click Play Audio
    await page.evaluate(() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            if (b.textContent.includes('Play') || b.textContent.includes('play')) { b.click(); return; }
        }
    });
    await new Promise(r => setTimeout(r, 3000));
    
    // Extract audio
    const audioData = await page.evaluate(() => {
        const audio = document.querySelector('audio');
        if (!audio) return null;
        return audio.src || (audio.querySelector('source') || {}).src || null;
    });
    
    if (!audioData) { log('No audio element'); return false; }
    
    if (audioData.startsWith('data:audio/')) {
        const match = audioData.match(/^data:audio\/([^;]+);base64,(.+)$/);
        if (!match) { log('Cannot parse audio base64'); return false; }
        
        const ext = match[1] === 'aac' ? 'aac' : match[1];
        const filePath = `/tmp/stf_audio_${Date.now()}.${ext}`;
        fs.writeFileSync(filePath, Buffer.from(match[2], 'base64'));
        log(`Audio saved: ${filePath} (${Buffer.from(match[2], 'base64').length} bytes)`);
        
        respond({status: 'audio_challenge', audio_file: filePath});
        
        const answer = await waitForAnswer();
        if (!answer) { log('No Whisper answer'); return false; }
        
        log(`Typing answer: "${answer}"`);
        const input = await page.$('input[type="text"]');
        if (input) {
            await input.click({clickCount: 3});
            await input.type(answer, {delay: 50});
        }
        
        // Click Confirm
        await page.evaluate(() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) { if (b.textContent.trim() === 'Confirm') { b.click(); return; } }
        });
        log('Clicked Confirm');
        
        await new Promise(r => setTimeout(r, 5000));
        
        // Wait for navigation (WAF redirects after solve)
        try { await page.waitForNavigation({waitUntil: 'networkidle2', timeout: 10000}); } catch {}
        
        const stillWaf = await page.evaluate(() => typeof window.gokuProps !== 'undefined');
        if (stillWaf) {
            log('Still on WAF after answer');
            return false;
        }
        
        log('WAF SOLVED!');
        respond({status: 'waf_solved'});
        return true;
    }
    
    return false;
}

async function exploreSPA(page) {
    log('Exploring SPA...');
    
    // Get home page data
    const homeData = await page.evaluate(() => ({
        url: window.location.href,
        title: document.title,
        bodyText: document.body.innerText.substring(0, 8000),
        scripts: Array.from(document.querySelectorAll('script[src]')).map(s => s.src),
        links: Array.from(document.querySelectorAll('a[href]')).map(a => ({href: a.href, text: a.textContent.trim()})),
        forms: Array.from(document.querySelectorAll('input, select, button, textarea, label')).map(el => ({
            tag: el.tagName, type: el.type, name: el.name, id: el.id,
            placeholder: el.placeholder, text: el.textContent?.trim()?.substring(0,100),
        })),
        framework: window.__remixContext ? 'Remix' : window.__NEXT_DATA__ ? 'Next.js' : 'React/Other',
        remixManifest: window.__remixManifest ? JSON.stringify(window.__remixManifest).substring(0,5000) : null,
        remixContext: window.__remixContext ? JSON.stringify(window.__remixContext).substring(0,5000) : null,
    }));
    
    // Save full HTML
    const homeHtml = await page.content();
    fs.writeFileSync('/tmp/stf_home.html', homeHtml);
    
    // Navigate to different routes
    const routes = ['/escolha-de-modelo', '/emitir-certidao', '/consulta', '/pesquisa', '/certidao'];
    const routeData = {};
    
    for (const route of routes) {
        log(`Trying route: ${route}`);
        try {
            await page.goto(TARGET + route, {waitUntil: 'networkidle2', timeout: 10000});
            await new Promise(r => setTimeout(r, 2000));
            
            const data = await page.evaluate(() => ({
                url: window.location.href,
                title: document.title,
                bodyText: document.body.innerText.substring(0, 5000),
                forms: Array.from(document.querySelectorAll('input, select, button, textarea, label')).map(el => ({
                    tag: el.tagName, type: el.type, name: el.name, id: el.id,
                    placeholder: el.placeholder, text: el.textContent?.trim()?.substring(0,100),
                    value: el.value, forAttr: el.getAttribute?.('for'),
                })),
                selects: Array.from(document.querySelectorAll('select')).map(s => ({
                    name: s.name, id: s.id,
                    options: Array.from(s.options).map(o => ({value: o.value, text: o.textContent.trim()})),
                })),
                links: Array.from(document.querySelectorAll('a[href]')).map(a => ({href: a.href, text: a.textContent.trim()})),
                radioButtons: Array.from(document.querySelectorAll('input[type="radio"]')).map(r => ({
                    name: r.name, value: r.value, id: r.id, checked: r.checked,
                    label: r.closest('label')?.textContent?.trim() || document.querySelector(`label[for="${r.id}"]`)?.textContent?.trim(),
                })),
                checkboxes: Array.from(document.querySelectorAll('input[type="checkbox"]')).map(c => ({
                    name: c.name, value: c.value, id: c.id, checked: c.checked,
                    label: c.closest('label')?.textContent?.trim() || document.querySelector(`label[for="${c.id}"]`)?.textContent?.trim(),
                })),
            }));
            
            routeData[route] = data;
            
            // Save HTML
            const html = await page.content();
            const safeName = route.replace(/\//g, '_');
            fs.writeFileSync(`/tmp/stf${safeName}.html`, html);
            
            log(`  URL: ${data.url}, Forms: ${data.forms.length}, Text: ${data.bodyText.substring(0,100)}...`);
        } catch (e) {
            routeData[route] = {error: e.message};
            log(`  Error: ${e.message}`);
        }
    }
    
    respond({status: 'spa_mapped', data: {home: homeData, routes: routeData}});
    return {home: homeData, routes: routeData};
}

async function emitCertidao(page, cpfCnpj, spaMap) {
    if (!cpfCnpj) {
        log('No CPF/CNPJ provided, skipping emission');
        return null;
    }
    
    log(`Emitting certidão for: ${cpfCnpj}`);
    
    // Navigate to escolha-de-modelo first
    await page.goto(TARGET + '/escolha-de-modelo', {waitUntil: 'networkidle2', timeout: 10000});
    await new Promise(r => setTimeout(r, 2000));
    
    // Check what's on the page and interact
    const pageState = await page.evaluate(() => ({
        bodyText: document.body.innerText,
        inputs: Array.from(document.querySelectorAll('input')).map(i => ({type: i.type, name: i.name, id: i.id, placeholder: i.placeholder})),
        buttons: Array.from(document.querySelectorAll('button')).map(b => ({text: b.textContent.trim(), type: b.type, disabled: b.disabled})),
        selects: Array.from(document.querySelectorAll('select')).map(s => ({
            name: s.name, id: s.id,
            options: Array.from(s.options).map(o => ({value: o.value, text: o.textContent.trim()})),
        })),
        radios: Array.from(document.querySelectorAll('input[type="radio"]')).map(r => ({
            name: r.name, value: r.value, id: r.id,
            label: r.closest('label')?.textContent?.trim() || document.querySelector(`label[for="${r.id}"]`)?.textContent?.trim(),
        })),
    }));
    
    log(`Page state: ${JSON.stringify(pageState).substring(0, 1000)}`);
    respond({status: 'page_state', data: pageState});
    
    return pageState;
}

(async () => {
    log('Launching stealth Chrome...');
    const browser = await puppeteer.launch({
        headless: false,
        executablePath: CHROME,
        args: [
            '--no-sandbox','--disable-dev-shm-usage','--disable-gpu',
            '--window-size=1200,900','--no-first-run','--disable-extensions',
            '--disable-sync','--mute-audio','--disable-infobars',
            '--password-store=basic','--disable-blink-features=AutomationControlled',
        ],
        ignoreDefaultArgs: ['--enable-automation'],
        defaultViewport: null,
        ignoreHTTPSErrors: true,
    });

    const page = (await browser.pages())[0] || await browser.newPage();
    
    // Intercept XHR/fetch calls
    const apiCalls = [];
    page.on('response', async resp => {
        const url = resp.url();
        if (url.includes('/api/') || url.includes('/certid') || url.includes('.json')) {
            try {
                const ct = resp.headers()['content-type'] || '';
                if (ct.includes('json') || ct.includes('text')) {
                    const body = await resp.text().catch(() => '');
                    apiCalls.push({url, status: resp.status(), ct, body: body.substring(0, 2000)});
                    log(`API: ${resp.status()} ${url.substring(0, 100)}`);
                }
            } catch {}
        }
    });
    
    log(`Navigating to ${TARGET}`);
    await page.goto(TARGET, {waitUntil: 'networkidle2', timeout: 30000});
    
    // Solve WAF
    const wafOk = await solveWAF(page);
    if (!wafOk) {
        log('WAF solve failed');
        respond({status: 'error', error: 'waf_solve_failed'});
        await browser.close();
        process.exit(1);
    }
    
    // Explore SPA
    const spaMap = await exploreSPA(page);
    
    // Emit certidão if CPF provided
    if (CPF_CNPJ) {
        await emitCertidao(page, CPF_CNPJ, spaMap);
    }
    
    // Save API calls
    fs.writeFileSync('/tmp/stf_api_calls.json', JSON.stringify(apiCalls, null, 2));
    
    respond({status: 'complete', apiCalls: apiCalls.length});
    
    await browser.close();
})().catch(e => {
    log('Fatal: ' + e.message);
    respond({status: 'error', error: e.message});
    process.exit(1);
});

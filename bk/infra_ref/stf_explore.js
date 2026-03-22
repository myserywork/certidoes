/**
 * STF SPA Explorer — Resolve WAF + mapeia a SPA
 * Resultado salvo em /tmp/stf_spa_map.json
 */
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');
const readline = require('readline');
puppeteer.use(StealthPlugin());

const CHROME = '/usr/bin/google-chrome';
const TARGET = 'https://certidoes.stf.jus.br';
const OUTPUT = '/tmp/stf_spa_map.json';

function log(msg) { process.stderr.write(`[STF-EXPLORE][${new Date().toTimeString().slice(0,8)}] ${msg}\n`); }

(async () => {
    log('Launching stealth Chrome...');
    const browser = await puppeteer.launch({
        headless: false,
        executablePath: CHROME,
        args: [
            '--no-sandbox','--disable-dev-shm-usage','--disable-gpu',
            '--window-size=1200,800','--no-first-run','--disable-extensions',
            '--disable-sync','--mute-audio','--disable-infobars',
            '--password-store=basic','--disable-blink-features=AutomationControlled',
        ],
        ignoreDefaultArgs: ['--enable-automation'],
        defaultViewport: null,
        ignoreHTTPSErrors: true,
    });

    const page = (await browser.pages())[0] || await browser.newPage();
    
    // Intercept network requests to capture API calls
    const apiCalls = [];
    await page.setRequestInterception(true);
    page.on('request', req => {
        const url = req.url();
        if (url.includes('/api/') || url.includes('/certid') || url.includes('/emitir') || url.includes('/consulta')) {
            apiCalls.push({method: req.method(), url, postData: req.postData()});
        }
        req.continue();
    });
    
    page.on('response', async resp => {
        const url = resp.url();
        if (url.includes('/api/') || url.includes('.json') || url.includes('/certid')) {
            try {
                const ct = resp.headers()['content-type'] || '';
                if (ct.includes('json')) {
                    const body = await resp.text();
                    apiCalls.push({type: 'response', url, status: resp.status(), body: body.substring(0, 2000)});
                }
            } catch {}
        }
    });

    log(`Navigating to ${TARGET}`);
    await page.goto(TARGET, {waitUntil: 'networkidle2', timeout: 30000});
    
    const hasGoku = await page.evaluate(() => typeof window.gokuProps !== 'undefined');
    
    if (hasGoku) {
        log('WAF detected, solving via audio...');
        
        await new Promise(r => setTimeout(r, 2000));
        
        // Click Begin
        log('Clicking Begin...');
        await page.evaluate(() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) { if (b.textContent.trim() === 'Begin') { b.click(); return; } }
        });
        await new Promise(r => setTimeout(r, 3000));
        
        // Click audio
        log('Clicking audio button...');
        await page.evaluate(() => {
            const btns = document.querySelectorAll('button.btn-icon, button');
            for (const b of btns) {
                const img = b.querySelector('img');
                if (img && img.alt && img.alt.includes('audio')) { b.click(); return; }
            }
        });
        await new Promise(r => setTimeout(r, 3000));
        
        // Click Play Audio
        log('Clicking Play Audio...');
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
        
        if (audioData && audioData.startsWith('data:audio/')) {
            const match = audioData.match(/^data:audio\/([^;]+);base64,(.+)$/);
            if (match) {
                const ext = match[1] === 'aac' ? 'aac' : match[1];
                const filePath = `/tmp/stf_explore_audio.${ext}`;
                fs.writeFileSync(filePath, Buffer.from(match[2], 'base64'));
                log(`Audio saved: ${filePath}`);
                
                // Signal Python to transcribe
                process.stdout.write(JSON.stringify({status: 'need_whisper', audio_file: filePath}) + '\n');
                
                // Wait for answer on stdin
                const rl = readline.createInterface({input: process.stdin});
                const answer = await new Promise(resolve => {
                    rl.on('line', line => {
                        try { const m = JSON.parse(line.trim()); if (m.answer !== undefined) resolve(m.answer); } catch {}
                    });
                    setTimeout(() => resolve(''), 30000);
                });
                rl.close();
                
                if (answer) {
                    log(`Whisper answer: "${answer}"`);
                    const input = await page.$('input[type="text"]');
                    if (input) {
                        await input.click();
                        await input.type(answer, {delay: 50});
                    }
                    
                    await page.evaluate(() => {
                        const btns = document.querySelectorAll('button');
                        for (const b of btns) { if (b.textContent.trim() === 'Confirm') { b.click(); return; } }
                    });
                    log('Clicked Confirm');
                    
                    await new Promise(r => setTimeout(r, 5000));
                    await page.waitForNavigation({waitUntil: 'networkidle2', timeout: 15000}).catch(() => {});
                }
            }
        }
    }
    
    // Now we should be past WAF — explore the SPA
    const currentUrl = page.url();
    const title = await page.title();
    log(`Post-WAF — URL: ${currentUrl}, Title: ${title}`);
    
    const stillWaf = await page.evaluate(() => typeof window.gokuProps !== 'undefined');
    if (stillWaf) {
        log('STILL ON WAF! Solver failed.');
        fs.writeFileSync(OUTPUT, JSON.stringify({error: 'WAF not solved'}, null, 2));
        await browser.close();
        process.exit(1);
    }
    
    // Map the SPA
    log('Mapping SPA...');
    
    const spaData = await page.evaluate(() => {
        const result = {};
        
        // HTML content
        result.bodyText = document.body.innerText.substring(0, 5000);
        result.title = document.title;
        result.url = window.location.href;
        
        // Scripts
        result.scripts = Array.from(document.querySelectorAll('script[src]')).map(s => s.src);
        result.inlineScripts = Array.from(document.querySelectorAll('script:not([src])')).map(s => s.textContent.substring(0, 500));
        
        // Links
        result.links = Array.from(document.querySelectorAll('a[href]')).map(a => ({href: a.href, text: a.textContent.trim()}));
        
        // Router links (React Router)
        result.routerLinks = Array.from(document.querySelectorAll('[data-discover], a[data-discover]')).map(a => ({href: a.href || a.getAttribute('to'), text: a.textContent.trim()}));
        
        // Forms
        result.forms = Array.from(document.querySelectorAll('input, select, button, textarea')).map(el => ({
            tag: el.tagName, type: el.type, name: el.name, id: el.id,
            placeholder: el.placeholder, className: el.className?.substring?.(0,80),
            text: el.textContent?.trim()?.substring(0,80), value: el.value,
        }));
        
        // Framework detection
        if (window.__remixContext) result.framework = 'Remix';
        else if (window.__NEXT_DATA__) result.framework = 'Next.js';
        else if (document.querySelector('[ng-app]')) result.framework = 'Angular';
        else if (document.querySelector('#root')) result.framework = 'React';
        else result.framework = 'Unknown';
        
        // App state
        try { result.remixContext = window.__remixContext ? JSON.stringify(window.__remixContext).substring(0, 3000) : null; } catch {}
        try { result.nextData = window.__NEXT_DATA__ ? JSON.stringify(window.__NEXT_DATA__).substring(0, 3000) : null; } catch {}
        
        // Meta tags
        result.meta = Array.from(document.querySelectorAll('meta')).map(m => ({name: m.name, content: m.content, property: m.getAttribute('property')}));
        
        // All URLs in page source
        const htmlSrc = document.documentElement.outerHTML;
        result.apiEndpoints = [...new Set((htmlSrc.match(/["'](\/api\/[^"']+)["']/g) || []).map(s => s.replace(/["']/g, '')))];
        result.allPaths = [...new Set((htmlSrc.match(/["'](\/[a-z][\w/-]+)["']/g) || []).map(s => s.replace(/["']/g, '')))].filter(p => !p.includes('.css') && !p.includes('.png'));
        
        return result;
    });
    
    // Try navigating to /escolha-de-modelo
    log('Navigating to /escolha-de-modelo...');
    await page.goto(TARGET + '/escolha-de-modelo', {waitUntil: 'networkidle2', timeout: 15000}).catch(() => {});
    await new Promise(r => setTimeout(r, 3000));
    
    const escolhaData = await page.evaluate(() => ({
        url: window.location.href,
        title: document.title,
        bodyText: document.body.innerText.substring(0, 5000),
        forms: Array.from(document.querySelectorAll('input, select, button, textarea, label')).map(el => ({
            tag: el.tagName, type: el.type, name: el.name, id: el.id,
            placeholder: el.placeholder, text: el.textContent?.trim()?.substring(0,100),
            value: el.value, className: el.className?.substring?.(0,80),
            forAttr: el.getAttribute('for'),
        })),
        links: Array.from(document.querySelectorAll('a[href]')).map(a => ({href: a.href, text: a.textContent.trim()})),
        selects: Array.from(document.querySelectorAll('select')).map(s => ({
            name: s.name, id: s.id,
            options: Array.from(s.options).map(o => ({value: o.value, text: o.textContent.trim()})),
        })),
    }));
    
    // Try navigating to /emitir-certidao
    log('Navigating to /emitir-certidao...');
    await page.goto(TARGET + '/emitir-certidao', {waitUntil: 'networkidle2', timeout: 15000}).catch(() => {});
    await new Promise(r => setTimeout(r, 3000));
    
    const emitirData = await page.evaluate(() => ({
        url: window.location.href,
        title: document.title,
        bodyText: document.body.innerText.substring(0, 5000),
        forms: Array.from(document.querySelectorAll('input, select, button, textarea, label')).map(el => ({
            tag: el.tagName, type: el.type, name: el.name, id: el.id,
            placeholder: el.placeholder, text: el.textContent?.trim()?.substring(0,100),
        })),
    }));
    
    // Full HTML of current page
    const fullHtml = await page.content();
    
    const result = {
        homePage: spaData,
        escolhaDeModelo: escolhaData,
        emitirCertidao: emitirData,
        apiCalls,
        fullHtmlLength: fullHtml.length,
    };
    
    fs.writeFileSync(OUTPUT, JSON.stringify(result, null, 2));
    fs.writeFileSync('/tmp/stf_spa_html.html', fullHtml);
    log(`Results saved to ${OUTPUT}`);
    
    await browser.close();
    process.stdout.write(JSON.stringify({status: 'done', output: OUTPUT}) + '\n');
})().catch(e => {
    log('Fatal: ' + e.message);
    process.exit(1);
});

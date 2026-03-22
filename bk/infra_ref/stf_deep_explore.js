/**
 * STF Deep Explorer — Resolve WAF + Wait for Vue + Extract SPA structure
 * Protocol: JSON lines stdout/stdin (Whisper integration)
 */
const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const fs = require('fs');
const readline = require('readline');
puppeteer.use(StealthPlugin());

const CHROME = '/usr/bin/google-chrome';
const TARGET = 'https://certidoes.stf.jus.br';

function log(msg) { process.stderr.write(`[STF-DEEP][${new Date().toTimeString().slice(0,8)}] ${msg}\n`); }
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

async function solveWAF(page) {
    const hasGoku = await page.evaluate(() => typeof window.gokuProps !== 'undefined');
    if (!hasGoku) { respond({status: 'no_captcha'}); return true; }
    
    log('WAF detected...');
    await new Promise(r => setTimeout(r, 2000));
    
    await page.evaluate(() => { document.querySelectorAll('button').forEach(b => { if (b.textContent.trim()==='Begin') b.click(); }); });
    await new Promise(r => setTimeout(r, 3000));
    
    await page.evaluate(() => {
        document.querySelectorAll('button').forEach(b => {
            const img = b.querySelector('img');
            if (img && img.alt && img.alt.includes('audio')) b.click();
        });
    });
    await new Promise(r => setTimeout(r, 3000));
    
    await page.evaluate(() => { document.querySelectorAll('button').forEach(b => { if (b.textContent.includes('Play')) b.click(); }); });
    await new Promise(r => setTimeout(r, 3000));
    
    const audioData = await page.evaluate(() => {
        const a = document.querySelector('audio');
        return a ? (a.src || (a.querySelector('source')||{}).src) : null;
    });
    
    if (!audioData || !audioData.startsWith('data:audio/')) return false;
    
    const match = audioData.match(/^data:audio\/([^;]+);base64,(.+)$/);
    if (!match) return false;
    
    const ext = match[1] === 'aac' ? 'aac' : match[1];
    const filePath = `/tmp/stf_deep_audio.${ext}`;
    fs.writeFileSync(filePath, Buffer.from(match[2], 'base64'));
    log(`Audio saved: ${filePath}`);
    
    respond({status: 'audio_challenge', audio_file: filePath});
    const answer = await waitStdin();
    if (!answer) return false;
    
    log(`Typing: "${answer}"`);
    const input = await page.$('input[type="text"]');
    if (input) { await input.click({clickCount:3}); await input.type(answer, {delay:50}); }
    
    await page.evaluate(() => { document.querySelectorAll('button').forEach(b => { if (b.textContent.trim()==='Confirm') b.click(); }); });
    log('Confirm clicked');
    
    await new Promise(r => setTimeout(r, 5000));
    try { await page.waitForNavigation({waitUntil:'networkidle2', timeout:10000}); } catch {}
    
    return !(await page.evaluate(() => typeof window.gokuProps !== 'undefined'));
}

(async () => {
    const browser = await puppeteer.launch({
        headless: false, executablePath: CHROME,
        args: ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--window-size=1400,900',
               '--no-first-run','--disable-extensions','--disable-sync','--mute-audio',
               '--disable-infobars','--password-store=basic','--disable-blink-features=AutomationControlled'],
        ignoreDefaultArgs: ['--enable-automation'],
        defaultViewport: null, ignoreHTTPSErrors: true,
    });

    const page = (await browser.pages())[0];
    
    // Capture XHR/fetch responses
    const xhrCalls = [];
    page.on('response', async resp => {
        const url = resp.url();
        const ct = resp.headers()['content-type'] || '';
        if ((ct.includes('json') || url.includes('/api/')) && !url.includes('awswaf') && !url.includes('recaptcha') && !url.includes('gstatic')) {
            try {
                const body = await resp.text().catch(() => '');
                xhrCalls.push({url, status: resp.status(), body: body.substring(0, 3000)});
                log(`XHR: ${resp.status()} ${url}`);
            } catch {}
        }
    });
    
    log(`Navigating to ${TARGET}`);
    await page.goto(TARGET, {waitUntil: 'networkidle2', timeout: 30000});
    
    if (!await solveWAF(page)) {
        respond({status: 'error', error: 'waf_failed'});
        await browser.close();
        process.exit(1);
    }
    
    respond({status: 'waf_solved'});
    log('WAF solved! Waiting for Vue to mount...');
    
    // Wait for Vue app to render - try waiting for content inside #app
    for (let i = 0; i < 10; i++) {
        const appContent = await page.evaluate(() => {
            const app = document.querySelector('#app');
            return app ? app.innerHTML.length : 0;
        });
        log(`Vue #app innerHTML length: ${appContent}`);
        if (appContent > 100) break;
        await new Promise(r => setTimeout(r, 1000));
    }
    
    // Get rendered DOM content
    const homeRendered = await page.evaluate(() => {
        const app = document.querySelector('#app');
        return {
            url: location.href,
            title: document.title,
            appInnerHTML: app ? app.innerHTML.substring(0, 10000) : 'NO #app',
            bodyText: document.body.innerText.substring(0, 8000),
            allText: document.body.textContent.substring(0, 8000),
            links: Array.from(document.querySelectorAll('a[href]')).map(a => ({href: a.href, text: a.textContent.trim()})),
            inputs: Array.from(document.querySelectorAll('input,select,textarea,button')).map(el => ({
                tag: el.tagName, type: el.type, name: el.name, id: el.id,
                placeholder: el.placeholder, text: el.textContent?.trim()?.substring(0,80),
                classes: el.className?.substring?.(0,100),
            })),
            imgs: Array.from(document.querySelectorAll('img')).map(i => ({src: i.src, alt: i.alt})),
        };
    });
    
    log(`Home bodyText: "${homeRendered.bodyText.substring(0,200)}"`);
    log(`Home links: ${homeRendered.links.length}`);
    log(`Home inputs: ${homeRendered.inputs.length}`);
    
    // Save home HTML
    const homeHtml = await page.content();
    fs.writeFileSync('/tmp/stf_deep_home.html', homeHtml);
    
    // Download and save the JS bundle (from within the session, past WAF)
    const bundleContent = await page.evaluate(async () => {
        const scripts = document.querySelectorAll('script[src]');
        for (const s of scripts) {
            if (s.src.includes('index.') && s.src.includes('.js')) {
                const resp = await fetch(s.src);
                return await resp.text();
            }
        }
        return null;
    });
    
    if (bundleContent) {
        fs.writeFileSync('/tmp/stf_bundle_real.js', bundleContent);
        log(`Bundle saved: ${bundleContent.length} bytes`);
    }
    
    // Navigate to /escolha-de-modelo and wait for render
    log('Navigating to /escolha-de-modelo...');
    await page.goto(TARGET + '/escolha-de-modelo', {waitUntil: 'networkidle2', timeout: 15000});
    
    for (let i = 0; i < 10; i++) {
        const len = await page.evaluate(() => document.querySelector('#app')?.innerHTML?.length || 0);
        if (len > 100) break;
        await new Promise(r => setTimeout(r, 1000));
    }
    
    const escolhaRendered = await page.evaluate(() => {
        const app = document.querySelector('#app');
        return {
            url: location.href,
            bodyText: document.body.innerText.substring(0, 8000),
            appHTML: app ? app.innerHTML.substring(0, 15000) : '',
            inputs: Array.from(document.querySelectorAll('input,select,textarea,button,label')).map(el => ({
                tag: el.tagName, type: el.type, name: el.name, id: el.id,
                placeholder: el.placeholder, text: el.textContent?.trim()?.substring(0,100),
                value: el.value, forAttr: el.getAttribute?.('for'),
                classes: el.className?.substring?.(0,100),
            })),
            selects: Array.from(document.querySelectorAll('select')).map(s => ({
                name: s.name, id: s.id,
                options: Array.from(s.options).map(o => ({value: o.value, text: o.textContent.trim()})),
            })),
            radios: Array.from(document.querySelectorAll('input[type="radio"]')).map(r => ({
                name: r.name, value: r.value, id: r.id,
                label: r.closest('label')?.textContent?.trim() || document.querySelector(`label[for="${r.id}"]`)?.textContent?.trim(),
            })),
            links: Array.from(document.querySelectorAll('a[href]')).map(a => ({href: a.href, text: a.textContent.trim()})),
        };
    });
    
    fs.writeFileSync('/tmp/stf_deep_escolha.html', await page.content());
    log(`Escolha bodyText: "${escolhaRendered.bodyText.substring(0,200)}"`);
    
    // Try clicking links or navigating within the SPA
    // If there are links in escolha, click the first certidao-related one
    if (escolhaRendered.links.length > 0) {
        log(`Found ${escolhaRendered.links.length} links on escolha page`);
        for (const link of escolhaRendered.links) {
            log(`  Link: ${link.text} -> ${link.href}`);
        }
    }
    
    // Check if there are radio/select options for model selection
    if (escolhaRendered.radios.length > 0) {
        log('Radio buttons found:');
        escolhaRendered.radios.forEach(r => log(`  ${r.value}: ${r.label}`));
    }
    if (escolhaRendered.selects.length > 0) {
        log('Selects found:');
        escolhaRendered.selects.forEach(s => {
            log(`  ${s.name}: ${s.options.map(o => o.text).join(', ')}`);
        });
    }
    
    // Final result
    const result = {
        home: homeRendered,
        escolha: escolhaRendered,
        xhrCalls,
        bundleSize: bundleContent ? bundleContent.length : 0,
    };
    
    fs.writeFileSync('/tmp/stf_deep_result.json', JSON.stringify(result, null, 2));
    respond({status: 'done', data: result});
    
    await browser.close();
})().catch(e => {
    log('Fatal: ' + e.message);
    respond({status: 'error', error: e.message});
    process.exit(1);
});

/**
 * Receita Federal PF - Puppeteer Stealth + 2captcha hCaptcha
 *
 * Uso: node receita_pf_solver.js <cpf> <dt_nascimento> <output_dir> [captcha_key]
 * Saida: JSON no stdout com {status, pdf_path, tipo_certidao, message}
 */
const pup = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
pup.use(StealthPlugin());
const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');

const cpf = process.argv[2];
const dtNascimento = process.argv[3];
const outputDir = process.argv[4] || require('os').tmpdir();
const captchaKey = process.argv[5] || process.env.CAPTCHA_API_KEY || '';

const URL = 'https://servicos.receitafederal.gov.br/servico/certidoes/#/home/cpf';
const log = (msg) => process.stderr.write(`[RECEITA-PF] ${msg}\n`);

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// 2captcha hCaptcha solver
async function solve2captcha(sitekey, pageUrl) {
  if (!captchaKey) return null;
  log(`Resolvendo hCaptcha via 2captcha...`);

  const submitUrl = `http://2captcha.com/in.php?key=${captchaKey}&method=hcaptcha&sitekey=${sitekey}&pageurl=${encodeURIComponent(pageUrl)}&json=1`;
  const submit = await fetch(submitUrl);
  const submitText = await submit.text();
  let captchaId;
  if (submitText.startsWith('OK|')) {
    captchaId = submitText.split('|')[1];
  } else {
    try { const d = JSON.parse(submitText); if (d.status===1) captchaId = d.request; else { log(`2captcha erro: ${d.request}`); return null; } }
    catch { log(`2captcha submit erro: ${submitText}`); return null; }
  }
  log(`2captcha ID: ${captchaId}`);

  for (let i = 0; i < 30; i++) {
    await sleep(5000);
    const resultUrl = `http://2captcha.com/res.php?key=${captchaKey}&action=get&id=${captchaId}`;
    const result = await fetch(resultUrl);
    const resultText = await result.text();
    if (resultText.startsWith('OK|')) { log('hCaptcha resolvido!'); return resultText.split('|').slice(1).join('|'); }
    if (resultText.includes('CAPCHA_NOT_READY')) continue;
    try { const d = JSON.parse(resultText); if (d.status===1) { log('hCaptcha resolvido!'); return d.request; } }
    catch { log(`2captcha poll: ${resultText}`); return null; }
  }
  return null;
}

(async () => {
  let browser;
  try {
    const launchOpts = {
      headless: process.platform === 'win32' ? 'new' : false,
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--window-size=1400,900'],
      ...(process.platform !== 'win32' ? { executablePath: '/usr/bin/google-chrome' } : {}),
    };

    browser = await pup.launch(launchOpts);
    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900 });

    // Interceptar requests para injetar captcha token
    let injectedToken = null;
    // Converter data DD/MM/YYYY -> YYYY-MM-DD
    const dtParts = dtNascimento.split('/');
    const dtISO = dtParts.length === 3 ? `${dtParts[2]}-${dtParts[1]}-${dtParts[0]}` : dtNascimento;

    await page.setRequestInterception(true);
    page.on('request', req => {
      if (req.url().includes('/api/Emissao/')) {
        const postData = req.postData();
        if (postData) {
          try {
            const body = JSON.parse(postData);
            // Corrigir data para ISO (Angular pode enviar errado)
            if (body.dataNascimento && body.dataNascimento.includes('/')) {
              const p = body.dataNascimento.split('/');
              body.dataNascimento = `${p[2]}-${p[1]}-${p[0]}`;
            }
            if (!body.dataNascimento || body.dataNascimento.length < 10) {
              body.dataNascimento = dtISO;
            }
            // Injetar captcha
            if (injectedToken) {
              body.captchaResponse = injectedToken;
            }
            log(`Intercepted: ${JSON.stringify(body).substring(0, 150)}`);
            req.continue({
              postData: JSON.stringify(body),
              headers: { ...req.headers(), 'captcha-response': injectedToken || '' },
            });
            return;
          } catch {}
        }
      }
      req.continue();
    });

    // Capturar resposta da API
    let apiResponse = null;
    page.on('response', async res => {
      if (res.url().includes('/api/Emissao/')) {
        try {
          const body = await res.text();
          apiResponse = { status: res.status(), body };
          log(`API Response: ${res.status()} ${res.url().split('/').pop()} => ${body.substring(0, 200)}`);
        } catch {}
      }
    });

    log('Navegando para Receita PF...');
    await page.goto(URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await sleep(3000);

    // Aceitar termos se aparecer
    try {
      const aceitar = await page.$x("//button[contains(text(), 'Aceito')]");
      if (aceitar.length > 0) {
        await aceitar[0].click();
        log('Termos aceitos');
        await sleep(2000);
      }
    } catch {}

    // Pegar sitekey do hCaptcha (pode nao aparecer imediatamente)
    let sitekey = '';
    // Tentar obter do env config
    try {
      const envResp = await page.evaluate(() => fetch('/servico/certidoes/api/env').then(r => r.json()));
      sitekey = envResp?.captchaPublicKey || '';
    } catch {}

    if (!sitekey) {
      try {
        sitekey = await page.evaluate(() => {
          const el = document.querySelector('[data-sitekey]');
          return el ? el.getAttribute('data-sitekey') : '';
        });
      } catch {}
    }

    if (!sitekey) sitekey = '4a65992d-58fc-4812-8b87-789f7e7c4c4b'; // Fallback known key
    log(`Sitekey: ${sitekey}`);

    // Resolver hCaptcha via 2captcha
    let captchaToken = null;
    if (sitekey && captchaKey) {
      captchaToken = await solve2captcha(sitekey, URL);
    }

    // Injetar token hCaptcha
    if (captchaToken) {
      await page.evaluate((token, sk) => {
        // 1. Se hcaptcha widget existe, setar resposta
        if (window.hcaptcha) {
          try {
            const ids = window.hcaptcha.getAllIds ? window.hcaptcha.getAllIds() : [];
            if (ids.length > 0) {
              ids.forEach(id => { try { window.hcaptcha.setResponse(token, id); } catch {} });
            }
          } catch {}
        }

        // 2. Setar textarea hidden (onde Angular le o token)
        document.querySelectorAll('textarea[name="h-captcha-response"]').forEach(t => {
          t.value = token; t.innerHTML = token;
          const ns = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
          ns.call(t, token);
          t.dispatchEvent(new Event('input', {bubbles: true}));
          t.dispatchEvent(new Event('change', {bubbles: true}));
        });

        // 3. Encontrar e chamar callback do Angular
        // O Angular web component registra callback em window
        const callbacks = Object.keys(window).filter(k => k.startsWith('hcaptchaCallback') || k.includes('captchaResolved'));
        callbacks.forEach(cb => { try { window[cb](token); } catch {} });

        // 4. Disparar custom events
        document.dispatchEvent(new CustomEvent('verified', { detail: { token } }));
        window.postMessage({ type: 'hcaptcha-verified', token }, '*');

        // 5. Cookie
        document.cookie = `h-captcha-response=${token}; path=/`;
      }, captchaToken, sitekey);
      injectedToken = captchaToken;
      log('Token injetado');
      await sleep(2000);
    } else if (sitekey && captchaKey) {
      log('hCaptcha nao apareceu na pagina — pode nao ser necessario');
    }

    // Preencher CPF — limpar e usar evaluate para setar direto
    log(`Preenchendo CPF: ${cpf}`);
    await page.waitForSelector('input[name="niContribuinte"]', { timeout: 10000 });
    await page.evaluate((v) => {
      const el = document.querySelector('input[name="niContribuinte"]');
      if (el) { el.value = ''; el.focus(); }
    }, cpf);
    await page.type('input[name="niContribuinte"]', cpf, { delay: 30 });
    await sleep(1000);

    // Preencher data nascimento — campo com mascara, usar evaluate + dispatch
    log(`Preenchendo nascimento: ${dtNascimento}`);
    await page.waitForSelector('input[name="dataNascimento"]', { timeout: 10000 });
    // Focar o campo, select all, delete, digitar limpo
    await page.focus('input[name="dataNascimento"]');
    await sleep(200);
    // Select all + delete
    await page.keyboard.down('Control');
    await page.keyboard.press('a');
    await page.keyboard.up('Control');
    await page.keyboard.press('Delete');
    await sleep(200);
    // Digitar a data completa com type() — inclui as barras
    // O campo pode ter mascara que adiciona / automatico, mas vamos tentar com formato completo
    await page.type('input[name="dataNascimento"]', dtNascimento, { delay: 100 });
    await sleep(500);
    // Tab para trigger blur
    await page.keyboard.press('Tab');
    await sleep(1000);

    const valorData = await page.evaluate(() => document.querySelector('input[name="dataNascimento"]')?.value);
    log(`Campo data apos type: "${valorData}"`);

    // Clicar botao de emitir/consultar via evaluate (XPath nao funciona no headless com Angular)
    log('Clicando botao...');
    const clickResult = await page.evaluate(() => {
      const allBtns = Array.from(document.querySelectorAll('button'));
      const labels = ['Emitir Certid', 'Consultar Certid', 'Nova Certid', 'Consultar'];
      for (const label of labels) {
        const btn = allBtns.find(b => b.textContent.includes(label));
        if (btn) { btn.click(); return `Clicou: ${btn.textContent.trim().substring(0, 30)}`; }
      }
      // Fallback: qualquer botao que nao seja Voltar
      const actionBtn = allBtns.find(b => !b.textContent.includes('Voltar') && !b.textContent.includes('Aceitar') && b.textContent.trim().length > 3);
      if (actionBtn) { actionBtn.click(); return `Fallback: ${actionBtn.textContent.trim().substring(0, 30)}`; }
      return 'nenhum botao';
    });
    log(clickResult);

    await sleep(5000);

    // Tratar modal de certidao existente
    try {
      const modalBtns = await page.$x("//button[contains(text(), 'Sim')]");
      if (modalBtns.length > 0) {
        await modalBtns[0].click();
        log('Modal confirmado');
        await sleep(3000);
      }
    } catch {}

    // Verificar resultado
    const bodyText = await page.evaluate(() => document.body.innerText);

    const erros = ['dados informados não conferem', 'data de nascimento', 'cpf não encontrado', 'erro'];
    for (const erro of erros) {
      if (bodyText.toLowerCase().includes(erro)) {
        console.log(JSON.stringify({ status: 'falha', message: `Receita: ${erro}` }));
        await browser.close();
        return;
      }
    }

    // Tentar baixar PDF via botão
    let pdfPath = null;
    try {
      const cdp = await page.target().createCDPSession();
      await cdp.send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: outputDir });

      // Clicar no botão de download se existir
      const downloadBtns = await page.$x("//button[contains(text(), 'Baixar')]");
      if (downloadBtns.length > 0) {
        await downloadBtns[0].click();
        log('Clicou baixar');
        await sleep(5000);

        // Verificar se PDF foi baixado
        const files = fs.readdirSync(outputDir).filter(f => f.endsWith('.pdf'));
        if (files.length > 0) {
          pdfPath = path.join(outputDir, files[files.length - 1]);
          log(`PDF baixado: ${pdfPath}`);
        }
      }
    } catch {}

    // Fallback: printToPDF se tem conteúdo de certidão
    if (!pdfPath) {
      const indicadores = ['certidão', 'nada consta', 'regular', 'positiva', 'negativa', 'débito'];
      const hasCertidao = indicadores.some(i => bodyText.toLowerCase().includes(i));

      if (hasCertidao) {
        log('Gerando PDF via printToPDF...');
        const cdp = await page.target().createCDPSession();
        const { data } = await cdp.send('Page.printToPDF', { printBackground: true, preferCSSPageSize: true });
        pdfPath = path.join(outputDir, `certidao_receita_pf_${cpf}.pdf`);
        fs.writeFileSync(pdfPath, Buffer.from(data, 'base64'));
        log(`PDF gerado: ${pdfPath} (${fs.statSync(pdfPath).size} bytes)`);
      } else {
        log('Pagina sem conteudo de certidao');
        console.log(JSON.stringify({ status: 'falha', message: 'Certidao nao disponivel' }));
        await browser.close();
        return;
      }
    }

    // Detectar tipo
    let tipoCertidao = 'desconhecida';
    if (bodyText.toLowerCase().includes('nada consta')) tipoCertidao = 'negativa';
    else if (bodyText.toLowerCase().includes('positiva')) tipoCertidao = 'positiva';

    console.log(JSON.stringify({
      status: 'sucesso',
      pdf_path: pdfPath,
      tipo_certidao: tipoCertidao,
      message: `Certidao Receita PF emitida (${tipoCertidao})`
    }));

    await browser.close();

  } catch (err) {
    log(`ERRO: ${err.message}`);
    console.log(JSON.stringify({ status: 'erro', message: err.message }));
    if (browser) await browser.close().catch(() => {});
  }
})();

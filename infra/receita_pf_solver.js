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
  const submitData = await submit.json();
  if (submitData.status !== 1) { log(`2captcha submit erro: ${submitData.request}`); return null; }

  const captchaId = submitData.request;
  log(`2captcha ID: ${captchaId}`);

  for (let i = 0; i < 30; i++) {
    await sleep(5000);
    const resultUrl = `http://2captcha.com/res.php?key=${captchaKey}&action=get&id=${captchaId}&json=1`;
    const result = await fetch(resultUrl);
    const resultData = await result.json();
    if (resultData.status === 1) {
      log(`hCaptcha resolvido!`);
      return resultData.request;
    }
    if (resultData.request !== 'CAPCHA_NOT_READY') { log(`2captcha erro: ${resultData.request}`); return null; }
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

    // Pegar sitekey do hCaptcha
    let sitekey = '';
    try {
      sitekey = await page.evaluate(() => {
        const el = document.querySelector('[data-sitekey]');
        return el ? el.getAttribute('data-sitekey') : '';
      });
      if (!sitekey) {
        sitekey = await page.evaluate(() => {
          const iframe = document.querySelector('iframe[src*="hcaptcha"]');
          if (iframe) {
            const match = iframe.src.match(/sitekey=([^&]+)/);
            return match ? match[1] : '';
          }
          return '';
        });
      }
    } catch {}

    log(`Sitekey: ${sitekey || 'nao encontrado'}`);

    // Resolver hCaptcha via 2captcha
    let captchaToken = null;
    if (sitekey && captchaKey) {
      captchaToken = await solve2captcha(sitekey, URL);
    }

    // Injetar token hCaptcha se resolvido
    if (captchaToken) {
      await page.evaluate((token) => {
        // Set hcaptcha response
        const textarea = document.querySelector('[name="h-captcha-response"]') || document.querySelector('textarea[name="h-captcha-response"]');
        if (textarea) { textarea.value = token; textarea.style.display = 'block'; }
        // Trigger callback
        if (window.hcaptcha) {
          try { window.hcaptcha.execute(); } catch {}
        }
        // Set cookie
        document.cookie = `h-captcha-response=${token}; path=/`;
      }, captchaToken);
      log('Token hCaptcha injetado');
      await sleep(1000);
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

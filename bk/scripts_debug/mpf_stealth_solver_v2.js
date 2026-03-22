const pup = require("puppeteer-extra");
const S = require("puppeteer-extra-plugin-stealth");
pup.use(S());

function log(msg) { process.stderr.write(msg + "\n"); }

(async () => {
  log("launch");
  const b = await pup.launch({
    headless: false,
    executablePath: "/usr/bin/google-chrome",
    args: [
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--no-first-run",
      "--mute-audio",
      "--password-store=basic",
      "--disable-blink-features=AutomationControlled",
      "--window-size=1920,1080",
      "--enable-gpu",
      "--use-gl=swiftshader",
      "--enable-webgl",
    ],
    ignoreDefaultArgs: ["--enable-automation"],
    defaultViewport: null,
    ignoreHTTPSErrors: true,
  });

  const pg = (await b.pages())[0] || await b.newPage();
  await pg.setUserAgent("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36");

  // Override WebGL to look like real GPU
  await pg.evaluateOnNewDocument(() => {
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
      if (parameter === 37445) return "Google Inc. (NVIDIA)";
      if (parameter === 37446) return "ANGLE (NVIDIA, NVIDIA GeForce RTX 4080 Direct3D11 vs_5_0 ps_5_0, D3D11)";
      return getParameter.call(this, parameter);
    };
    const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(parameter) {
      if (parameter === 37445) return "Google Inc. (NVIDIA)";
      if (parameter === 37446) return "ANGLE (NVIDIA, NVIDIA GeForce RTX 4080 Direct3D11 vs_5_0 ps_5_0, D3D11)";
      return getParameter2.call(this, parameter);
    };
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
  });

  log("open");
  await pg.goto(
    "https://aplicativos.mpf.mp.br/ouvidoria/app/cidadao/certidao",
    { waitUntil: "networkidle2", timeout: 30000 }
  );
  log("loaded");

  await new Promise(r => setTimeout(r, 3000));

  // Click "Emitir Certidão"
  await pg.evaluate(() => {
    document.querySelectorAll("button").forEach(b => {
      if (b.textContent && b.textContent.includes("Emitir")) b.click();
    });
  });
  log("clicked");

  // Wait for Turnstile to render and auto-solve
  let tk = "";
  const s = Date.now();
  const TIMEOUT = 55000;

  while (Date.now() - s < TIMEOUT) {
    try {
      tk = await pg.evaluate(() => {
        const i = document.querySelector("input[name=cf-turnstile-response]");
        if (i && i.value && i.value.length > 20) return i.value;
        return "";
      });
    } catch {}
    if (tk) break;
    await new Promise(r => setTimeout(r, 500));
  }

  await b.close();

  if (tk) {
    log("OK " + tk.length + "ch in " + ((Date.now()-s)/1000).toFixed(1) + "s");
    process.stdout.write(tk);
    process.exit(0);
  } else {
    log("FAIL after " + ((Date.now()-s)/1000).toFixed(1) + "s");
    process.exit(1);
  }
})().catch(e => {
  log("ERR:" + e.message);
  process.exit(1);
});

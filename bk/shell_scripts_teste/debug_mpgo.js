const puppeteer = require("puppeteer-extra");
const StealthPlugin = require("puppeteer-extra-plugin-stealth");
puppeteer.use(StealthPlugin());

function log(msg) { process.stderr.write("[DBG] " + msg + "\n"); }

(async () => {
    const browser = await puppeteer.launch({
        headless: false, executablePath: "/usr/bin/google-chrome",
        args: ["--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--window-size=1400,900",
               "--disable-blink-features=AutomationControlled"],
        ignoreDefaultArgs: ["--enable-automation"],
        defaultViewport: null, ignoreHTTPSErrors: true,
    });

    const page = (await browser.pages())[0] || await browser.newPage();
    await page.setUserAgent("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36");

    log("Navigating...");
    await page.goto("https://www.mpgo.mp.br/certidao", { waitUntil: "networkidle2", timeout: 30000 });
    await new Promise(r => setTimeout(r, 3000));

    const frames = page.frames();
    log("Frames: " + frames.length);
    frames.forEach((f, i) => log("  [" + i + "] " + f.url().substring(0, 120)));

    const rcFrame = frames.find(f => f.url().includes("recaptcha/api2/anchor"));
    if (rcFrame === undefined) { log("No anchor frame"); await browser.close(); return; }

    const frameElement = await page.$('iframe[title*="reCAPTCHA"]');
    if (frameElement) {
        const box = await frameElement.boundingBox();
        if (box) {
            await page.mouse.click(box.x + 28, box.y + 28);
            log("Clicked checkbox at " + box.x + "," + box.y);
        }
    }

    await new Promise(r => setTimeout(r, 6000));

    let token = await page.evaluate(() => {
        const ta = document.querySelector('textarea[name="g-recaptcha-response"]');
        return (ta && ta.value && ta.value.length > 20) ? ta.value : "";
    });
    log("Token after click: " + (token ? token.length + " chars" : "none"));

    if (token) {
        log("AUTO-SOLVED");
        await browser.close();
        return;
    }

    const allFrames = page.frames();
    const chFrame = allFrames.find(f => f.url().includes("recaptcha/api2/bframe"));
    if (chFrame) {
        log("Challenge frame found: " + chFrame.url().substring(0, 80));

        const hasAudio = await chFrame.evaluate(() => {
            const btn = document.querySelector("#recaptcha-audio-button");
            return btn ? { exists: true, visible: btn.offsetWidth > 0 } : { exists: false };
        });
        log("Audio button: " + JSON.stringify(hasAudio));

        const buttons = await chFrame.evaluate(() => {
            return Array.from(document.querySelectorAll("button")).map(b => ({
                id: b.id, cls: b.className.substring(0,50), text: b.textContent.trim().substring(0, 50),
                w: b.offsetWidth, h: b.offsetHeight
            }));
        });
        log("Buttons: " + JSON.stringify(buttons));

        const challengeInfo = await chFrame.evaluate(() => {
            const img = document.querySelector(".rc-image-tile-wrapper img");
            const audioResp = document.querySelector("#audio-response");
            const header = document.querySelector(".rc-imageselect-desc-no-canonical");
            const header2 = document.querySelector(".rc-imageselect-desc");
            return {
                hasImages: img ? true : false,
                hasAudioInput: audioResp ? true : false,
                headerText: (header || header2 || {}).textContent || "none"
            };
        });
        log("Challenge info: " + JSON.stringify(challengeInfo));
    } else {
        log("No challenge frame found");
    }

    await browser.close();
})().catch(e => { console.error(e.message); process.exit(1); });

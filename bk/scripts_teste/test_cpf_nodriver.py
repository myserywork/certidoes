#!/usr/bin/env python3
"""Test CPF Receita using nodriver (CDP-based, no WebDriver) + CLIP hCaptcha solver."""
import sys
import os
import time
import json
import re
import random
import asyncio

sys.path.insert(0, "/root/pedro_project")
os.environ.setdefault("DISPLAY", ":121")

CPF_URL = "https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/consultapublica.asp"
CPF = "27290000625"
DATA_NASC = "21111958"


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[ND][{ts}] {msg}", flush=True)


async def main():
    import nodriver as nd

    log("Starting nodriver browser...")
    browser = await nd.start(
        browser_args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--window-size=1280,900",
        ],
    )

    page = await browser.get(CPF_URL)
    await asyncio.sleep(4)

    # Define recaptchaCallback
    await page.evaluate("""
        window.recaptchaCallback = function(token) {
            document.getElementById('idCheckedReCaptcha').value = 'true';
        };
    """)

    # Random scroll to build motion data
    await page.evaluate("window.scrollTo(0, 100);")
    await asyncio.sleep(0.5)
    await page.evaluate("window.scrollTo(0, 0);")
    await asyncio.sleep(0.5)

    # Fill CPF
    cpf_input = await page.select("#txtCPF")
    await cpf_input.click()
    await asyncio.sleep(0.3)
    await cpf_input.send_keys(CPF)
    await asyncio.sleep(0.2)
    await page.evaluate("document.getElementById('txtCPF').blur()")
    await asyncio.sleep(0.5)

    # Fill date
    data_input = await page.select("#txtDataNascimento")
    await data_input.click()
    await asyncio.sleep(0.3)
    await data_input.send_keys(DATA_NASC)
    await asyncio.sleep(0.2)
    await page.evaluate("document.getElementById('txtDataNascimento').blur()")
    await asyncio.sleep(0.5)

    cpf_val = await page.evaluate("document.getElementById('txtCPF').value")
    data_val = await page.evaluate("document.getElementById('txtDataNascimento').value")
    log(f"Form filled: CPF={cpf_val}, Data={data_val}")

    # Find and click hCaptcha checkbox
    await asyncio.sleep(2)

    # Get all iframes
    iframes = await page.select_all("iframe")
    log(f"Found {len(iframes)} iframes")

    checkbox_frame = None
    for iframe in iframes:
        src = iframe.attrs.get("src", "")
        if "hcaptcha" in src or "newassets" in src:
            if "checkbox" in src or "frame=checkbox" in src:
                checkbox_frame = iframe
                break

    if not checkbox_frame:
        log("No hCaptcha checkbox iframe found, trying by attribute...")
        for iframe in iframes:
            src = iframe.attrs.get("src", "")
            if "hcaptcha" in src or "newassets" in src:
                checkbox_frame = iframe
                break

    if not checkbox_frame:
        log("FATAL: No hCaptcha iframe found")
        browser.stop()
        return

    log(f"Found checkbox iframe: {checkbox_frame.attrs.get('src', '')[:80]}")

    # Click the checkbox - need to get the frame content
    # With nodriver, we need to use CDP to interact with the iframe
    frame_id = checkbox_frame.frame_id
    if frame_id:
        log(f"Frame ID: {frame_id}")
        # Try clicking the checkbox within the frame
        try:
            # Navigate into the frame
            frame_page = checkbox_frame
            # Find checkbox inside frame
            cb = await frame_page.select("#checkbox")
            if cb:
                await cb.click()
                log("Clicked hCaptcha checkbox via frame")
            else:
                # Try clicking the iframe element itself
                await checkbox_frame.click()
                log("Clicked iframe element directly")
        except Exception as e:
            log(f"Frame click error: {e}, clicking iframe directly")
            await checkbox_frame.click()
    else:
        await checkbox_frame.click()
        log("Clicked iframe (no frame_id)")

    await asyncio.sleep(random.uniform(5, 7))

    # Check auto-solve
    token = await page.evaluate("""
        var t = document.querySelector('textarea[name="h-captcha-response"]');
        (t && t.value.length > 20) ? t.value : '';
    """)
    if token:
        log(f"Auto-solved! {len(token)} chars")
    else:
        log("Need to solve challenge...")
        # Import CLIP solver
        from infra.hcaptcha_solver import classify_images_clip

        for round_num in range(1, 6):
            log(f"--- Round {round_num} ---")

            # Find challenge iframe
            challenge_frame = None
            iframes = await page.select_all("iframe")
            for iframe in iframes:
                src = iframe.attrs.get("src", "")
                if ("hcaptcha" in src or "newassets" in src) and "frame=challenge" in src:
                    challenge_frame = iframe
                    break

            if not challenge_frame:
                token = await page.evaluate("""
                    var t = document.querySelector('textarea[name="h-captcha-response"]');
                    (t && t.value.length > 20) ? t.value : '';
                """)
                if token:
                    log(f"Solved after round {round_num-1}!")
                    break
                log("No challenge frame found")
                break

            # Get challenge data from the frame using CDP
            try:
                # Use page-level JS to get data from iframe
                challenge_data = await page.evaluate("""
                    (function() {
                        var frames = document.querySelectorAll('iframe');
                        for (var f of frames) {
                            var src = f.src || '';
                            if ((src.includes('hcaptcha') || src.includes('newassets')) && src.includes('challenge')) {
                                try {
                                    var doc = f.contentDocument || f.contentWindow.document;
                                    var promptEl = doc.querySelector('.prompt-text');
                                    var prompt = promptEl ? promptEl.textContent.trim() : '';

                                    var exampleEl = doc.querySelector('.prompt-padding .image, .challenge-example .image');
                                    var exampleUrl = '';
                                    if (exampleEl) {
                                        var bg = getComputedStyle(exampleEl).backgroundImage;
                                        var m = bg.match(/url\\("?(.+?)"?\\)/);
                                        if (m) exampleUrl = m[1];
                                    }

                                    var cells = doc.querySelectorAll('.task-image');
                                    var cellUrls = [];
                                    cells.forEach(function(cell) {
                                        var img = cell.querySelector('.image');
                                        var url = '';
                                        if (img) {
                                            var bg = getComputedStyle(img).backgroundImage;
                                            var m = bg.match(/url\\("?(.+?)"?\\)/);
                                            if (m) url = m[1];
                                        }
                                        cellUrls.push(url);
                                    });

                                    return {prompt: prompt, example: exampleUrl, cells: cellUrls, count: cells.length};
                                } catch(e) {
                                    return {error: 'cross-origin: ' + e.message};
                                }
                            }
                        }
                        return {error: 'no challenge frame'};
                    })()
                """)

                log(f"Challenge data: {json.dumps(challenge_data)[:200]}")

                if challenge_data.get("error"):
                    # Cross-origin - need CDP approach
                    log(f"Cross-origin error, trying CDP frame access...")

                    # Use CDP to access frame content
                    # Get frame tree
                    frame_tree = await page.send(nd.cdp.page.get_frame_tree())
                    log(f"Frame tree: {frame_tree}")

                    # For now, try screenshot-based approach as fallback
                    log("Cross-origin blocks direct frame access")
                    break

                prompt = challenge_data.get("prompt", "")
                cell_urls = challenge_data.get("cells", [])
                example_url = challenge_data.get("example", "")
                log(f"Prompt: '{prompt}', Cells: {len(cell_urls)}")

                # Download images
                import urllib.request
                img_paths = []
                for i, url in enumerate(cell_urls):
                    if url and url.startswith("http"):
                        path = f"/tmp/nd_r{round_num}_cell_{i}.png"
                        try:
                            urllib.request.urlretrieve(url, path)
                            img_paths.append(path)
                        except:
                            img_paths.append("")
                    else:
                        img_paths.append("")

                example_path = ""
                if example_url and example_url.startswith("http"):
                    example_path = f"/tmp/nd_r{round_num}_example.png"
                    try:
                        urllib.request.urlretrieve(example_url, example_path)
                    except:
                        example_path = ""

                log(f"Images: {len([p for p in img_paths if p])}/{len(cell_urls)}")

                # Classify
                clicks = classify_images_clip(prompt, img_paths, example_path)
                log(f"CLIP clicks: {clicks}")

                if not clicks:
                    # Skip
                    await page.evaluate("""
                        var frames = document.querySelectorAll('iframe');
                        for (var f of frames) {
                            if ((f.src||'').includes('challenge')) {
                                try { f.contentDocument.querySelector('.button-submit').click(); } catch(e) {}
                            }
                        }
                    """)
                    await asyncio.sleep(3)
                    continue

                # Click cells
                for idx in clicks:
                    await asyncio.sleep(random.uniform(0.3, 0.8))
                    await page.evaluate(f"""
                        var frames = document.querySelectorAll('iframe');
                        for (var f of frames) {{
                            if ((f.src||'').includes('challenge')) {{
                                try {{
                                    var cells = f.contentDocument.querySelectorAll('.task-image');
                                    if ({idx} < cells.length) cells[{idx}].click();
                                }} catch(e) {{}}
                            }}
                        }}
                    """)

                await asyncio.sleep(random.uniform(0.5, 1.0))

                # Submit
                await page.evaluate("""
                    var frames = document.querySelectorAll('iframe');
                    for (var f of frames) {
                        if ((f.src||'').includes('challenge')) {
                            try { f.contentDocument.querySelector('.button-submit').click(); } catch(e) {}
                        }
                    }
                """)

                await asyncio.sleep(random.uniform(3, 5))

                # Check token
                token = await page.evaluate("""
                    var t = document.querySelector('textarea[name="h-captcha-response"]');
                    (t && t.value.length > 20) ? t.value : '';
                """)
                if token:
                    log(f"Solved in round {round_num}! {len(token)} chars")
                    break

                log(f"Round {round_num} done, no token yet")

            except Exception as e:
                log(f"Round {round_num} error: {e}")
                import traceback
                traceback.print_exc()
                break

    if not token:
        log("FAILED to solve hCaptcha")
        browser.stop()
        return

    # Set form state
    await page.evaluate("document.getElementById('idCheckedReCaptcha').value = 'true';")

    # Re-fill if needed
    cpf_val = await page.evaluate("document.getElementById('txtCPF').value")
    if not cpf_val or len(cpf_val.replace('.','').replace('-','')) < 11:
        await page.evaluate(f"document.getElementById('txtCPF').value = '{CPF[:3]}.{CPF[3:6]}.{CPF[6:9]}-{CPF[9:]}';")

    data_val = await page.evaluate("document.getElementById('txtDataNascimento').value")
    if not data_val or len(data_val.replace('/','')) < 8:
        await page.evaluate("document.getElementById('txtDataNascimento').value = '21/11/1958';")

    form_state = await page.evaluate("""
        JSON.stringify({
            cpf: document.getElementById('txtCPF').value,
            data: document.getElementById('txtDataNascimento').value,
            checked: document.getElementById('idCheckedReCaptcha').value,
            token_len: (document.querySelector('textarea[name="h-captcha-response"]') || {value:''}).value.length
        })
    """)
    log(f"Form state: {form_state}")

    # Submit
    log("Submitting form...")
    submit_btn = await page.select("#id_submit")
    await submit_btn.click()

    await asyncio.sleep(6)

    # Check result
    url = page.url
    log(f"Result URL: {url}")

    if "Error=" in url:
        m = re.search(r'Error=(\d+)', url)
        log(f"ERROR: Error={m.group(1) if m else '?'}")
    else:
        html = await page.evaluate("document.documentElement.outerHTML")
        log(f"Page length: {len(html)}")
        nome_match = re.search(r'Nome.*?<[^>]*>([^<]+)', html)
        sit_match = re.search(r'Situa.*?Cadastral.*?<[^>]*>([^<]+)', html)
        if nome_match or sit_match:
            nome = nome_match.group(1).strip() if nome_match else ""
            situacao = sit_match.group(1).strip() if sit_match else ""
            log(f"SUCCESS! Nome: {nome}, Situacao: {situacao}")

    browser.stop()
    log("Browser closed")


if __name__ == "__main__":
    asyncio.run(main())

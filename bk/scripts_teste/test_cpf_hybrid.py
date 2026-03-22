#!/usr/bin/env python3
"""
Hybrid approach: solve hCaptcha in UC browser, then submit form via requests
with browser cookies. Also test submitting via browser with form.submit().
"""
import sys
import os
import time
import json
import re
import random
import requests as req_lib

sys.path.insert(0, "/root/pedro_project")
os.environ.setdefault("DISPLAY", ":0")

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

CPF_URL = "https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/consultapublica.asp"
SUBMIT_URL = "https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/ConsultaPublicaExibir.asp"
CPF = "27290000625"
CPF_FMT = "272.900.006-25"
DATA_NASC = "21/11/1958"


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[HYB][{ts}] {msg}", flush=True)


def human_type(driver, element, text):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))


def solve_hcaptcha(driver):
    from infra.hcaptcha_solver import classify_images_clip
    time.sleep(2)

    frames = driver.find_elements(By.TAG_NAME, "iframe")
    checkbox_frame = None
    for frame in frames:
        src = frame.get_attribute("src") or ""
        if "hcaptcha" in src or "newassets" in src:
            try:
                driver.switch_to.frame(frame)
                has_cb = len(driver.find_elements(By.ID, "checkbox")) > 0
                driver.switch_to.default_content()
                if has_cb:
                    checkbox_frame = frame
                    break
            except:
                driver.switch_to.default_content()

    if not checkbox_frame:
        log("No hCaptcha checkbox found")
        return None

    driver.switch_to.frame(checkbox_frame)
    cb = driver.find_element(By.ID, "checkbox")
    ActionChains(driver).move_to_element(cb).pause(0.2).click().perform()
    log("Clicked hCaptcha checkbox")
    driver.switch_to.default_content()
    time.sleep(random.uniform(4, 6))

    token = driver.execute_script("""
        var t = document.querySelector('textarea[name="h-captcha-response"]');
        return (t && t.value.length > 20) ? t.value : '';
    """)
    if token:
        log(f"Auto-solved! {len(token)} chars")
        return token

    for round_num in range(1, 6):
        log(f"--- Round {round_num} ---")
        challenge_frame = None
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in frames:
            src = frame.get_attribute("src") or ""
            if "hcaptcha" in src or "newassets" in src:
                try:
                    driver.switch_to.frame(frame)
                    has_grid = len(driver.find_elements(By.CSS_SELECTOR, ".task-grid, .challenge-container")) > 0
                    driver.switch_to.default_content()
                    if has_grid:
                        challenge_frame = frame
                        break
                except:
                    driver.switch_to.default_content()

        if not challenge_frame:
            token = driver.execute_script("""
                var t = document.querySelector('textarea[name="h-captcha-response"]');
                return (t && t.value.length > 20) ? t.value : '';
            """)
            if token:
                return token
            return None

        driver.switch_to.frame(challenge_frame)
        try:
            prompt = driver.find_element(By.CSS_SELECTOR, ".prompt-text").text.strip()
        except:
            prompt = ""
        log(f"Prompt: '{prompt}'")

        example_path = ""
        try:
            example_el = driver.find_element(By.CSS_SELECTOR, ".prompt-padding .image, .challenge-example .image")
            bg = driver.execute_script("return getComputedStyle(arguments[0]).backgroundImage", example_el)
            m = re.search(r'url\("?(.+?)"?\)', bg)
            if m:
                import urllib.request
                example_path = f"/tmp/hyb_r{round_num}_example.png"
                urllib.request.urlretrieve(m.group(1), example_path)
        except:
            pass

        cells = driver.find_elements(By.CSS_SELECTOR, ".task-image")
        img_paths = []
        for i, cell in enumerate(cells):
            try:
                img_el = cell.find_element(By.CSS_SELECTOR, ".image")
                bg = driver.execute_script("return getComputedStyle(arguments[0]).backgroundImage", img_el)
                m = re.search(r'url\("?(.+?)"?\)', bg)
                if m:
                    import urllib.request
                    path = f"/tmp/hyb_r{round_num}_cell_{i}.png"
                    urllib.request.urlretrieve(m.group(1), path)
                    img_paths.append(path)
                else:
                    img_paths.append("")
            except:
                img_paths.append("")

        driver.switch_to.default_content()
        clicks = classify_images_clip(prompt, img_paths, example_path)
        log(f"CLIP clicks: {clicks}")

        if not clicks:
            driver.switch_to.frame(challenge_frame)
            try:
                driver.execute_script("document.querySelector('.button-submit').click();")
            except:
                pass
            driver.switch_to.default_content()
            time.sleep(3)
            continue

        driver.switch_to.frame(challenge_frame)
        cells = driver.find_elements(By.CSS_SELECTOR, ".task-image")
        for idx in clicks:
            if idx < len(cells):
                time.sleep(random.uniform(0.3, 0.8))
                driver.execute_script("arguments[0].click();", cells[idx])
        time.sleep(random.uniform(0.5, 1.0))
        try:
            btn = driver.find_element(By.CSS_SELECTOR, ".button-submit")
            driver.execute_script("arguments[0].click();", btn)
        except:
            pass
        driver.switch_to.default_content()
        time.sleep(random.uniform(3, 5))

        token = driver.execute_script("""
            var t = document.querySelector('textarea[name="h-captcha-response"]');
            return (t && t.value.length > 20) ? t.value : '';
        """)
        if token:
            log(f"Solved in round {round_num}! {len(token)} chars")
            return token

    return None


def main():
    log("Starting UC browser...")
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,900")

    driver = uc.Chrome(options=options)

    try:
        log("Navigating to Receita...")
        driver.get(CPF_URL)
        time.sleep(3)

        # Define recaptchaCallback
        driver.execute_script("""
            window.recaptchaCallback = function(token) {
                document.getElementById('idCheckedReCaptcha').value = 'true';
            };
        """)

        # Fill form
        cpf_input = driver.find_element(By.ID, "txtCPF")
        cpf_input.click()
        time.sleep(0.3)
        human_type(driver, cpf_input, CPF)
        driver.execute_script("document.getElementById('txtCPF').blur()")
        time.sleep(0.5)

        data_input = driver.find_element(By.ID, "txtDataNascimento")
        data_input.click()
        time.sleep(0.3)
        human_type(driver, data_input, "21111958")
        driver.execute_script("document.getElementById('txtDataNascimento').blur()")
        time.sleep(0.5)

        log(f"Form: CPF={cpf_input.get_attribute('value')}, Data={data_input.get_attribute('value')}")

        # Solve hCaptcha
        token = solve_hcaptcha(driver)
        if not token:
            log("FAILED to solve hCaptcha")
            return

        log(f"Token obtained: {len(token)} chars")

        # Get all browser cookies
        cookies = driver.get_cookies()
        log(f"Browser cookies: {json.dumps([{c['name']:c['value']} for c in cookies])}")

        # Get the current page URL to check for any redirects
        current_url = driver.current_url
        log(f"Current URL: {current_url}")

        # ==== METHOD 1: Submit via JavaScript form.submit() (bypass ValidarDados) ====
        log("=== Method 1: form.submit() via JS ===")
        driver.execute_script("""
            document.getElementById('idCheckedReCaptcha').value = 'true';
            // Make sure CPF and date are filled
            var cpf = document.getElementById('txtCPF');
            var data = document.getElementById('txtDataNascimento');
            if (!cpf.value || cpf.value.replace(/\\D/g,'').length < 11) cpf.value = '272.900.006-25';
            if (!data.value || data.value.replace(/\\D/g,'').length < 8) data.value = '21/11/1958';
        """)

        # Add compat fields
        driver.execute_script("""
            var token = document.querySelector('textarea[name="h-captcha-response"]').value;
            var form = document.getElementById('theForm');
            var f1 = document.createElement('input');
            f1.type = 'hidden'; f1.name = 'g-recaptcha-response'; f1.value = token;
            form.appendChild(f1);
            var f2 = document.createElement('input');
            f2.type = 'hidden'; f2.name = 'h-recaptcha-response'; f2.id = 'h-recaptcha-response'; f2.value = token;
            form.appendChild(f2);
        """)

        # Try using XMLHttpRequest to see the actual response
        result = driver.execute_script("""
            return new Promise(function(resolve) {
                var form = document.getElementById('theForm');
                var formData = new FormData(form);

                // Log what we're sending
                var entries = {};
                for (var pair of formData.entries()) {
                    entries[pair[0]] = (pair[1] || '').toString().substring(0, 100);
                }

                var xhr = new XMLHttpRequest();
                xhr.open('POST', form.action, true);
                xhr.onload = function() {
                    resolve({
                        status: xhr.status,
                        url: xhr.responseURL,
                        body: xhr.responseText.substring(0, 2000),
                        entries: entries
                    });
                };
                xhr.onerror = function() {
                    resolve({error: 'network error'});
                };
                xhr.send(formData);
            });
        """)

        log(f"XHR status: {result.get('status')}")
        log(f"XHR URL: {result.get('url')}")
        log(f"XHR entries: {json.dumps(result.get('entries', {}))}")

        body = result.get('body', '')
        if 'Error=' in (result.get('url', '') or ''):
            m = re.search(r'Error=(\d+)', result.get('url', ''))
            log(f"XHR Error={m.group(1) if m else '?'}")
        elif 'Nome' in body:
            nome_match = re.search(r'Nome.*?<[^>]*>([^<]+)', body)
            if nome_match:
                log(f"XHR SUCCESS! Nome: {nome_match.group(1).strip()}")

        # Check if the server returns different errors based on captcha field name
        # Also check if idCheckedReCaptcha matters
        log(f"XHR body preview: {body[:500]}")

    finally:
        driver.quit()
        log("Browser closed")


if __name__ == "__main__":
    main()

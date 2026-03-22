"""
Debug CPF Receita: solve hCaptcha, capture token, decode JWT, and check response.
"""
import time
import json
import re
import random
import sys
import os
import subprocess
import urllib.request
import tempfile
import base64

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

CPF_URL = "https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/consultapublica.asp"
CPF = "27290000625"
DATA_NASC = "21111958"
CDP_PORT = 9222
TEMP_DIR = os.path.join(tempfile.gettempdir(), "hcaptcha_cpf")


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[DBG][{ts}] {msg}", flush=True)


def classify_via_wsl(prompt, img_paths, example_path=""):
    wsl_paths = []
    for p in img_paths:
        if p:
            wsl_p = p.replace("\\", "/").replace("C:", "/mnt/c")
            wsl_paths.append(wsl_p)
        else:
            wsl_paths.append("")
    wsl_example = ""
    if example_path:
        wsl_example = example_path.replace("\\", "/").replace("C:", "/mnt/c")

    py_code = f'''
import sys, json
sys.path.insert(0, "/root/pedro_project")
from infra.hcaptcha_solver import classify_images_clip
clicks = classify_images_clip({json.dumps(prompt)}, {json.dumps(wsl_paths)}, {json.dumps(wsl_example)})
print(json.dumps(clicks))
'''
    try:
        result = subprocess.run(
            ["wsl", "-d", "Ubuntu-22.04", "-u", "root", "--", "python3", "-c", py_code],
            capture_output=True, text=True, timeout=60
        )
        for line in result.stdout.strip().split("\n"):
            if line.strip().startswith("["):
                return json.loads(line.strip())
        if result.stdout.strip():
            try:
                return json.loads(result.stdout.strip().split("\n")[-1])
            except:
                pass
        return []
    except:
        return []


def main():
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{CDP_PORT}")

    log("Connecting to Chrome...")
    driver = webdriver.Chrome(options=chrome_options)
    log(f"Connected! webdriver={driver.execute_script('return navigator.webdriver')}")

    # Navigate
    driver.get(CPF_URL)
    time.sleep(4)

    # Define callback
    driver.execute_script("""
        window.recaptchaCallback = function(token) {
            document.getElementById('idCheckedReCaptcha').value = 'true';
        };
    """)

    # Fill form
    cpf_input = driver.find_element(By.ID, "txtCPF")
    cpf_input.click()
    time.sleep(0.3)
    for c in CPF:
        cpf_input.send_keys(c)
        time.sleep(random.uniform(0.05, 0.12))
    driver.execute_script("document.getElementById('txtCPF').blur()")
    time.sleep(0.5)

    data_input = driver.find_element(By.ID, "txtDataNascimento")
    data_input.click()
    time.sleep(0.3)
    for c in DATA_NASC:
        data_input.send_keys(c)
        time.sleep(random.uniform(0.05, 0.12))
    driver.execute_script("document.getElementById('txtDataNascimento').blur()")
    time.sleep(0.5)

    log(f"Form: CPF={cpf_input.get_attribute('value')}, Data={data_input.get_attribute('value')}")

    # Solve hCaptcha
    time.sleep(2)
    frames = driver.find_elements(By.TAG_NAME, "iframe")
    checkbox_frame = None
    for frame in frames:
        src = frame.get_attribute("src") or ""
        if "hcaptcha" in src or "newassets" in src:
            try:
                driver.switch_to.frame(frame)
                if driver.find_elements(By.ID, "checkbox"):
                    checkbox_frame = frame
                    driver.switch_to.default_content()
                    break
                driver.switch_to.default_content()
            except:
                driver.switch_to.default_content()

    if not checkbox_frame:
        log("No checkbox!")
        return

    driver.switch_to.frame(checkbox_frame)
    cb = driver.find_element(By.ID, "checkbox")
    ActionChains(driver).move_to_element(cb).pause(0.2).click().perform()
    log("Clicked checkbox")
    driver.switch_to.default_content()
    time.sleep(5)

    os.makedirs(TEMP_DIR, exist_ok=True)

    token = None
    for round_num in range(1, 10):
        token = driver.execute_script("""
            var t = document.querySelector('textarea[name="h-captcha-response"]');
            return (t && t.value.length > 20) ? t.value : '';
        """)
        if token:
            log(f"Token obtained! {len(token)} chars")
            break

        log(f"--- Round {round_num} ---")
        challenge_frame = None
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in frames:
            src = frame.get_attribute("src") or ""
            if "hcaptcha" in src or "newassets" in src:
                try:
                    driver.switch_to.frame(frame)
                    if driver.find_elements(By.CSS_SELECTOR, ".task-grid, .challenge-container"):
                        challenge_frame = frame
                        driver.switch_to.default_content()
                        break
                    driver.switch_to.default_content()
                except:
                    driver.switch_to.default_content()

        if not challenge_frame:
            log("No challenge frame")
            break

        driver.switch_to.frame(challenge_frame)
        try:
            prompt = driver.find_element(By.CSS_SELECTOR, ".prompt-text").text.strip()
        except:
            prompt = ""

        example_path = ""
        try:
            el = driver.find_element(By.CSS_SELECTOR, ".prompt-padding .image, .challenge-example .image")
            bg = driver.execute_script("return getComputedStyle(arguments[0]).backgroundImage", el)
            m = re.search(r'url\("?(.+?)"?\)', bg)
            if m:
                example_path = os.path.join(TEMP_DIR, f"r{round_num}_ex.png")
                urllib.request.urlretrieve(m.group(1), example_path)
        except:
            pass

        cells = driver.find_elements(By.CSS_SELECTOR, ".task-image")
        img_paths = []
        for i, cell in enumerate(cells):
            try:
                img = cell.find_element(By.CSS_SELECTOR, ".image")
                bg = driver.execute_script("return getComputedStyle(arguments[0]).backgroundImage", img)
                m = re.search(r'url\("?(.+?)"?\)', bg)
                if m:
                    p = os.path.join(TEMP_DIR, f"r{round_num}_c{i}.png")
                    urllib.request.urlretrieve(m.group(1), p)
                    img_paths.append(p)
                else:
                    img_paths.append("")
            except:
                img_paths.append("")

        driver.switch_to.default_content()
        clicks = classify_via_wsl(prompt, img_paths, example_path)
        log(f"R{round_num}: '{prompt[:50]}' | cells={len(cells)} | clicks={clicks}")

        if not clicks:
            driver.switch_to.frame(challenge_frame)
            driver.execute_script("document.querySelector('.button-submit').click();")
            driver.switch_to.default_content()
            time.sleep(3)
            continue

        driver.switch_to.frame(challenge_frame)
        cells = driver.find_elements(By.CSS_SELECTOR, ".task-image")
        for idx in clicks:
            if idx < len(cells):
                time.sleep(random.uniform(0.3, 0.7))
                driver.execute_script("arguments[0].click();", cells[idx])
        time.sleep(0.5)
        try:
            driver.execute_script("document.querySelector('.button-submit').click();")
        except:
            pass
        driver.switch_to.default_content()
        time.sleep(4)

    if not token:
        token = driver.execute_script("""
            var t = document.querySelector('textarea[name="h-captcha-response"]');
            return (t && t.value.length > 20) ? t.value : '';
        """)

    if not token:
        log("FAILED to solve hCaptcha")
        return

    # Decode JWT
    log(f"\n=== TOKEN ANALYSIS ===")
    log(f"Token length: {len(token)}")
    log(f"Token prefix: {token[:10]}")
    jwt = token[3:] if token.startswith("P1_") else token
    parts = jwt.split(".")
    log(f"JWT parts: {len(parts)}")

    if len(parts) >= 2:
        try:
            header_b64 = parts[0] + "=" * (4 - len(parts[0]) % 4)
            header = base64.urlsafe_b64decode(header_b64)
            log(f"Header: {header.decode()}")
        except Exception as e:
            log(f"Header error: {e}")

        try:
            payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            try:
                payload = json.loads(payload_bytes)
                log(f"Payload (JSON): {json.dumps(payload, indent=2)[:1000]}")
            except:
                log(f"Payload (hex first 100): {payload_bytes.hex()[:200]}")
                log(f"Payload (raw first 100): {payload_bytes[:100]}")
        except Exception as e:
            log(f"Payload error: {e}")

    # Now try submitting via fetch() and check response
    log(f"\n=== SUBMISSION TEST ===")

    # Method 1: Direct form submit via button click
    driver.execute_script("""
        document.getElementById('idCheckedReCaptcha').value = 'true';
        var token = document.querySelector('textarea[name="h-captcha-response"]').value;
        var form = document.getElementById('theForm');

        // Add compat fields
        var f1 = document.createElement('input');
        f1.type = 'hidden'; f1.name = 'g-recaptcha-response'; f1.value = token;
        form.appendChild(f1);
        var f2 = document.createElement('input');
        f2.type = 'hidden'; f2.name = 'h-recaptcha-response'; f2.id = 'h-recaptcha-response'; f2.value = token;
        form.appendChild(f2);

        var cpf = document.getElementById('txtCPF');
        var data = document.getElementById('txtDataNascimento');
        if (!cpf.value || cpf.value.replace(/\\D/g,'').length < 11) cpf.value = '272.900.006-25';
        if (!data.value || data.value.replace(/\\D/g,'').length < 8) data.value = '21/11/1958';
    """)

    # Try XHR with URL-encoded data (NOT FormData which uses multipart)
    xhr_result = driver.execute_script("""
        return new Promise(function(resolve) {
            var token = document.querySelector('textarea[name="h-captcha-response"]').value;
            var params = 'idCheckedReCaptcha=true' +
                '&txtCPF=' + encodeURIComponent(document.getElementById('txtCPF').value) +
                '&txtDataNascimento=' + encodeURIComponent(document.getElementById('txtDataNascimento').value) +
                '&h-captcha-response=' + encodeURIComponent(token) +
                '&g-recaptcha-response=' + encodeURIComponent(token) +
                '&Enviar=Consultar';

            var xhr = new XMLHttpRequest();
            xhr.open('POST', 'ConsultaPublicaExibir.asp', true);
            xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
            xhr.onload = function() {
                resolve({
                    status: xhr.status,
                    url: xhr.responseURL,
                    body: xhr.responseText.substring(0, 3000),
                    headers: xhr.getAllResponseHeaders()
                });
            };
            xhr.onerror = function() { resolve({error: 'network'}); };
            xhr.send(params);
        });
    """)

    log(f"XHR status: {xhr_result.get('status')}")
    log(f"XHR URL: {xhr_result.get('url', '')}")

    body = xhr_result.get("body", "")
    if "Error=" in xhr_result.get("url", ""):
        m = re.search(r"Error=(\d+)", xhr_result.get("url", ""))
        log(f"XHR Error={m.group(1) if m else '?'}")

        # Check error message in body
        msg_match = re.search(r'mensagemErro">(.*?)<', body)
        if msg_match:
            log(f"Error msg: {msg_match.group(1)}")
    elif "Nome" in body:
        nome_match = re.search(r'Nome.*?<[^>]*>([^<]+)', body)
        sit_match = re.search(r'Situa.*?Cadastral.*?<[^>]*>([^<]+)', body)
        if nome_match or sit_match:
            nome = nome_match.group(1).strip() if nome_match else ""
            sit = sit_match.group(1).strip() if sit_match else ""
            log(f"SUCCESS! Nome: {nome}, Situacao: {sit}")
    else:
        log(f"Unknown response. URL: {xhr_result.get('url', '')}")
        log(f"Body preview: {body[:500]}")

    log("Done")


if __name__ == "__main__":
    main()

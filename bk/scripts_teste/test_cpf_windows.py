#!/usr/bin/env python3
"""
CPF Receita solver using Windows Chrome via CDP (no WebDriver).
Starts Chrome natively on Windows, connects via Chrome DevTools Protocol.
This bypasses ALL automation detection since Chrome runs normally.
"""
import sys
import os
import time
import json
import re
import random
import subprocess
import socket
import signal

sys.path.insert(0, "/root/pedro_project")

import requests

CPF_URL = "https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/consultapublica.asp"
CPF = "27290000625"
CPF_FMT = "272.900.006-25"
DATA_NASC_DIGITS = "21111958"
DATA_NASC_FMT = "21/11/1958"
CDP_PORT = 9222
# Use Windows Chrome path (accessible from WSL via /mnt/c/)
CHROME_WIN = "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"
# User data dir in Windows temp
USER_DATA_DIR = "C:\\Users\\workstation\\AppData\\Local\\Temp\\chrome_cpf_profile"


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[WIN][{ts}] {msg}", flush=True)


def is_port_open(port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(("127.0.0.1", port))
            return True
    except:
        return False


def cdp_send(ws_url, method, params=None, session_id=None):
    """Send a CDP command via HTTP endpoint."""
    # We'll use the /json/protocol for simple commands
    pass


class CDPSession:
    """Simple CDP session using HTTP endpoints (no WebSocket)."""

    def __init__(self, port=9222):
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self._msg_id = 0

    def get_targets(self):
        r = requests.get(f"{self.base}/json/list")
        return r.json()

    def get_page_target(self):
        targets = self.get_targets()
        for t in targets:
            if t.get("type") == "page":
                return t
        return None

    def navigate(self, url):
        """Navigate using /json/navigate (Chrome extension)."""
        # Use the debugger protocol via WebSocket for proper CDP
        pass

    def evaluate(self, expression, target_id=None):
        """Evaluate JS using CDP Runtime.evaluate via WebSocket."""
        pass


def main():
    # Kill any existing Chrome debug instances
    os.system("pkill -f 'chrome.*remote-debugging-port' 2>/dev/null")
    time.sleep(1)

    # Start Windows Chrome with remote debugging
    log("Starting Windows Chrome with remote debugging...")
    chrome_cmd = [
        str(CHROME_WIN),
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={USER_DATA_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-default-apps",
        "--disable-popup-blocking",
        "--disable-translate",
        "--window-size=1280,900",
        CPF_URL,
    ]

    proc = subprocess.Popen(chrome_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log(f"Chrome PID: {proc.pid}")

    # Wait for CDP port to be available
    for _ in range(30):
        if is_port_open(CDP_PORT):
            log("CDP port is open!")
            break
        time.sleep(1)
    else:
        log("CDP port not available after 30s")
        proc.kill()
        return

    time.sleep(3)

    # Now use Selenium to connect to the running Chrome via CDP
    # This is the cleanest way to automate — Chrome has NO webdriver flag
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains

    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{CDP_PORT}")

    log("Connecting to Chrome via debugger...")
    try:
        driver = webdriver.Chrome(options=chrome_options)
    except Exception as e:
        log(f"Connection failed: {e}")
        # Try with explicit chromedriver
        from selenium.webdriver.chrome.service import Service
        # Need Windows chromedriver for Windows Chrome
        log("Trying alternative connection method...")
        proc.kill()
        return

    log(f"Connected! URL: {driver.current_url}")

    try:
        # Check if we're on the right page
        if "receita" not in driver.current_url.lower():
            log("Navigating to Receita...")
            driver.get(CPF_URL)
            time.sleep(4)

        # Check navigator.webdriver
        wd = driver.execute_script("return navigator.webdriver")
        log(f"navigator.webdriver = {wd}")

        # Define callback
        driver.execute_script("""
            window.recaptchaCallback = function(token) {
                document.getElementById('idCheckedReCaptcha').value = 'true';
            };
        """)

        # Fill CPF
        cpf_input = driver.find_element(By.ID, "txtCPF")
        cpf_input.click()
        time.sleep(0.3)
        for char in CPF:
            cpf_input.send_keys(char)
            time.sleep(random.uniform(0.05, 0.15))
        driver.execute_script("document.getElementById('txtCPF').blur()")
        time.sleep(0.5)

        # Fill date
        data_input = driver.find_element(By.ID, "txtDataNascimento")
        data_input.click()
        time.sleep(0.3)
        for char in DATA_NASC_DIGITS:
            data_input.send_keys(char)
            time.sleep(random.uniform(0.05, 0.15))
        driver.execute_script("document.getElementById('txtDataNascimento').blur()")
        time.sleep(0.5)

        log(f"Form: CPF={cpf_input.get_attribute('value')}, Data={data_input.get_attribute('value')}")

        # Click hCaptcha checkbox
        time.sleep(2)
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        log(f"Found {len(frames)} iframes")

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
            log("No hCaptcha checkbox found!")
            return

        driver.switch_to.frame(checkbox_frame)
        cb = driver.find_element(By.ID, "checkbox")
        ActionChains(driver).move_to_element(cb).pause(0.2).click().perform()
        log("Clicked hCaptcha checkbox")
        driver.switch_to.default_content()

        # Wait longer for potential auto-solve (real browser might auto-solve!)
        log("Waiting for hCaptcha response (might auto-solve on real browser)...")
        for wait_secs in range(15):
            time.sleep(1)
            token = driver.execute_script("""
                var t = document.querySelector('textarea[name="h-captcha-response"]');
                return (t && t.value.length > 20) ? t.value : '';
            """)
            if token:
                log(f"hCaptcha solved after {wait_secs+1}s! Token: {len(token)} chars")
                break

        if not token:
            log("Not auto-solved, need visual challenge...")
            # Solve with CLIP
            from infra.hcaptcha_solver import classify_images_clip

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
                        log(f"Solved!")
                        break
                    log("No challenge frame")
                    break

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
                        example_path = f"/tmp/win_r{round_num}_example.png"
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
                            path = f"/tmp/win_r{round_num}_cell_{i}.png"
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
                    driver.execute_script("document.querySelector('.button-submit').click();")
                    driver.switch_to.default_content()
                    time.sleep(3)
                    continue

                driver.switch_to.frame(challenge_frame)
                cells = driver.find_elements(By.CSS_SELECTOR, ".task-image")
                for idx in clicks:
                    if idx < len(cells):
                        time.sleep(random.uniform(0.3, 0.8))
                        driver.execute_script("arguments[0].click();", cells[idx])
                time.sleep(0.5)
                try:
                    btn = driver.find_element(By.CSS_SELECTOR, ".button-submit")
                    driver.execute_script("arguments[0].click();", btn)
                except:
                    pass
                driver.switch_to.default_content()
                time.sleep(4)

                token = driver.execute_script("""
                    var t = document.querySelector('textarea[name="h-captcha-response"]');
                    return (t && t.value.length > 20) ? t.value : '';
                """)
                if token:
                    log(f"Solved in round {round_num}! {len(token)} chars")
                    break

        if not token:
            log("FAILED to solve hCaptcha")
            return

        # Prepare form and submit
        driver.execute_script("""
            document.getElementById('idCheckedReCaptcha').value = 'true';
            var cpf = document.getElementById('txtCPF');
            var data = document.getElementById('txtDataNascimento');
            if (!cpf.value || cpf.value.replace(/\\D/g,'').length < 11) cpf.value = '272.900.006-25';
            if (!data.value || data.value.replace(/\\D/g,'').length < 8) data.value = '21/11/1958';

            // Add compat fields
            var token = document.querySelector('textarea[name="h-captcha-response"]').value;
            var form = document.getElementById('theForm');
            var f1 = document.createElement('input');
            f1.type = 'hidden'; f1.name = 'g-recaptcha-response'; f1.value = token;
            form.appendChild(f1);
            var f2 = document.createElement('input');
            f2.type = 'hidden'; f2.name = 'h-recaptcha-response'; f2.id = 'h-recaptcha-response'; f2.value = token;
            form.appendChild(f2);
        """)

        log("Submitting form...")
        driver.find_element(By.ID, "id_submit").click()
        time.sleep(6)

        url = driver.current_url
        log(f"Result URL: {url}")

        if "Error=" in url:
            m = re.search(r'Error=(\d+)', url)
            log(f"ERROR: Error={m.group(1) if m else '?'}")
        else:
            html = driver.page_source
            nome_match = re.search(r'Nome.*?<[^>]*>([^<]+)', html)
            sit_match = re.search(r'Situa.*?Cadastral.*?<[^>]*>([^<]+)', html)
            if nome_match or sit_match:
                nome = nome_match.group(1).strip() if nome_match else ""
                situacao = sit_match.group(1).strip() if sit_match else ""
                log(f"SUCCESS! Nome: {nome}, Situacao: {situacao}")
            with open("/tmp/cpf_win_result.html", "w") as f:
                f.write(html)

    finally:
        try:
            driver.quit()
        except:
            pass
        try:
            proc.kill()
        except:
            pass
        log("Done")


if __name__ == "__main__":
    main()

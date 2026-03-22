"""
Step 1: Connect to Windows Chrome, navigate to Receita, fill form, click hCaptcha.
Check if hCaptcha auto-solves on a real Windows browser.
Run this on Windows Python (not WSL).
"""
import time
import json
import re
import random
import sys
import os

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

CPF_URL = "https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/consultapublica.asp"
CPF = "27290000625"
DATA_NASC = "21111958"

def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[WIN][{ts}] {msg}", flush=True)

def main():
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")

    log("Connecting to Chrome via CDP...")
    driver = webdriver.Chrome(options=chrome_options)
    log(f"Connected! URL: {driver.current_url}")

    # Check navigator.webdriver
    wd = driver.execute_script("return navigator.webdriver")
    log(f"navigator.webdriver = {wd}")

    # Navigate to Receita
    log("Navigating to Receita...")
    driver.get(CPF_URL)
    time.sleep(4)

    # Define recaptchaCallback
    driver.execute_script("""
        window.recaptchaCallback = function(token) {
            document.getElementById('idCheckedReCaptcha').value = 'true';
            console.log('recaptchaCallback called, token: ' + token.length + ' chars');
        };
    """)

    # Fill CPF
    cpf_input = driver.find_element(By.ID, "txtCPF")
    cpf_input.click()
    time.sleep(0.3)
    for char in CPF:
        cpf_input.send_keys(char)
        time.sleep(random.uniform(0.05, 0.12))
    driver.execute_script("document.getElementById('txtCPF').blur()")
    time.sleep(0.5)

    # Fill date
    data_input = driver.find_element(By.ID, "txtDataNascimento")
    data_input.click()
    time.sleep(0.3)
    for char in DATA_NASC:
        data_input.send_keys(char)
        time.sleep(random.uniform(0.05, 0.12))
    driver.execute_script("document.getElementById('txtDataNascimento').blur()")
    time.sleep(0.5)

    log(f"Form: CPF={cpf_input.get_attribute('value')}, Data={data_input.get_attribute('value')}")

    # Find hCaptcha checkbox
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

    # Click checkbox
    driver.switch_to.frame(checkbox_frame)
    cb = driver.find_element(By.ID, "checkbox")
    ActionChains(driver).move_to_element(cb).pause(0.2).click().perform()
    log("Clicked hCaptcha checkbox")
    driver.switch_to.default_content()

    # Wait for auto-solve (real Windows browser might auto-solve!)
    log("Waiting for hCaptcha response...")
    token = ""
    for i in range(30):
        time.sleep(1)
        token = driver.execute_script("""
            var t = document.querySelector('textarea[name="h-captcha-response"]');
            return (t && t.value.length > 20) ? t.value : '';
        """)
        if token:
            log(f"hCaptcha SOLVED after {i+1}s! Token: {len(token)} chars")
            break
        if (i + 1) % 5 == 0:
            log(f"Still waiting... {i+1}s")

    if not token:
        # Check if there's a challenge
        has_challenge = False
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in frames:
            src = frame.get_attribute("src") or ""
            if ("hcaptcha" in src or "newassets" in src) and "challenge" in src:
                has_challenge = True
                break
        log(f"No auto-solve. Challenge present: {has_challenge}")

        if has_challenge:
            # Save challenge info for CLIP solving on WSL
            log("Challenge detected - need CLIP solver (on WSL)")
            # Extract challenge data
            for frame in frames:
                src = frame.get_attribute("src") or ""
                if ("hcaptcha" in src or "newassets" in src):
                    try:
                        driver.switch_to.frame(frame)
                        prompt_el = driver.find_elements(By.CSS_SELECTOR, ".prompt-text")
                        if prompt_el:
                            log(f"Prompt: '{prompt_el[0].text}'")
                        cells = driver.find_elements(By.CSS_SELECTOR, ".task-image")
                        if cells:
                            log(f"Cells: {len(cells)}")
                            # Get image URLs
                            urls = []
                            for cell in cells:
                                try:
                                    img = cell.find_element(By.CSS_SELECTOR, ".image")
                                    bg = driver.execute_script("return getComputedStyle(arguments[0]).backgroundImage", img)
                                    m = re.search(r'url\("?(.+?)"?\)', bg)
                                    if m:
                                        urls.append(m.group(1))
                                except:
                                    pass
                            log(f"Image URLs: {len(urls)}")
                            # Save URLs to file for WSL CLIP
                            with open(r"C:\Users\workstation\Desktop\PEDRO_PROJECT\PEDRO_PROJECT\challenge_data.json", "w") as f:
                                json.dump({"prompt": prompt_el[0].text if prompt_el else "", "urls": urls}, f)
                            log("Challenge data saved to challenge_data.json")
                        driver.switch_to.default_content()
                        break
                    except Exception as e:
                        log(f"Error reading challenge: {e}")
                        driver.switch_to.default_content()

        log("Need to solve challenge with CLIP - see challenge_data.json")
        # Don't close browser - let the user/WSL script solve it
        return

    # Token obtained! Now submit the form
    log("Preparing to submit...")

    # Set form state
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

    log("Submitting...")
    driver.find_element(By.ID, "id_submit").click()
    time.sleep(6)

    url = driver.current_url
    log(f"Result URL: {url}")

    if "Error=" in url:
        m = re.search(r'Error=(\d+)', url)
        log(f"ERROR: Error={m.group(1) if m else '?'}")
        html = driver.page_source
        with open(r"C:\Users\workstation\Desktop\PEDRO_PROJECT\PEDRO_PROJECT\cpf_win_error.html", "w", encoding="utf-8") as f:
            f.write(html)
    else:
        html = driver.page_source
        log(f"Page length: {len(html)}")
        nome_match = re.search(r'Nome.*?<[^>]*>([^<]+)', html)
        sit_match = re.search(r'Situa.*?Cadastral.*?<[^>]*>([^<]+)', html)
        if nome_match or sit_match:
            nome = nome_match.group(1).strip() if nome_match else ""
            situacao = sit_match.group(1).strip() if sit_match else ""
            log(f"SUCCESS! Nome: {nome}, Situacao: {situacao}")
        with open(r"C:\Users\workstation\Desktop\PEDRO_PROJECT\PEDRO_PROJECT\cpf_win_result.html", "w", encoding="utf-8") as f:
            f.write(html)
        log("Result saved!")

    # Note: don't quit() to keep the browser open
    log("Done. Browser is still open.")

if __name__ == "__main__":
    main()

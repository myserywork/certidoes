#!/usr/bin/env python3
"""Test CPF Receita using undetected-chromedriver (system Chrome 146) + CLIP hCaptcha solver.
Adds realistic mouse movements and proper callback handling."""
import sys
import os
import time
import json
import re
import random

sys.path.insert(0, "/root/pedro_project")
os.environ.setdefault("DISPLAY", ":121")

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

CPF_URL = "https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/consultapublica.asp"
CPF = "27290000625"
DATA_NASC = "21111958"


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[UC2][{ts}] {msg}", flush=True)


def human_type(driver, element, text, min_delay=0.05, max_delay=0.15):
    """Type text with human-like random delays."""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(min_delay, max_delay))


def random_mouse_move(driver, actions):
    """Perform random mouse movements to look more human."""
    for _ in range(random.randint(2, 5)):
        x = random.randint(100, 800)
        y = random.randint(100, 600)
        actions.move_by_offset(x - 400, y - 300).perform()
        time.sleep(random.uniform(0.1, 0.3))


def solve_hcaptcha(driver):
    """Solve hCaptcha within the UC browser using CLIP."""
    from infra.hcaptcha_solver import classify_images_clip

    time.sleep(2)

    # Find checkbox iframe
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
        log("No hCaptcha checkbox found")
        return False

    # Click checkbox with realistic mouse movement
    actions = ActionChains(driver)
    actions.move_to_element(checkbox_frame).perform()
    time.sleep(random.uniform(0.3, 0.7))

    driver.switch_to.frame(checkbox_frame)
    cb = driver.find_element(By.ID, "checkbox")
    actions = ActionChains(driver)
    actions.move_to_element(cb).pause(random.uniform(0.1, 0.3)).click().perform()
    log("Clicked hCaptcha checkbox")
    driver.switch_to.default_content()

    time.sleep(random.uniform(4, 6))

    # Check auto-solve
    token = driver.execute_script("""
        var t = document.querySelector('textarea[name="h-captcha-response"]');
        return (t && t.value.length > 20) ? t.value : '';
    """)
    if token:
        log(f"Auto-solved! {len(token)} chars")
        return True

    # Solve challenge rounds
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
                log(f"Solved after round {round_num-1}!")
                return True
            log("No challenge frame found")
            return False

        driver.switch_to.frame(challenge_frame)

        # Get prompt
        try:
            prompt_el = driver.find_element(By.CSS_SELECTOR, ".prompt-text")
            prompt = prompt_el.text.strip()
        except:
            prompt = ""
        log(f"Prompt: '{prompt}'")

        # Get example image
        example_path = ""
        try:
            example_el = driver.find_element(By.CSS_SELECTOR, ".prompt-padding .image, .challenge-example .image")
            bg = driver.execute_script(
                "return getComputedStyle(arguments[0]).backgroundImage", example_el
            )
            m = re.search(r'url\("?(.+?)"?\)', bg)
            if m:
                import urllib.request
                example_url = m.group(1)
                example_path = f"/tmp/uc2_r{round_num}_example.png"
                urllib.request.urlretrieve(example_url, example_path)
        except Exception as e:
            log(f"Example image error: {e}")

        # Get cell images
        cells = driver.find_elements(By.CSS_SELECTOR, ".task-image")
        log(f"Cells: {len(cells)}")

        img_paths = []
        for i, cell in enumerate(cells):
            try:
                img_el = cell.find_element(By.CSS_SELECTOR, ".image")
                bg = driver.execute_script(
                    "return getComputedStyle(arguments[0]).backgroundImage", img_el
                )
                m = re.search(r'url\("?(.+?)"?\)', bg)
                if m:
                    import urllib.request
                    cell_url = m.group(1)
                    cell_path = f"/tmp/uc2_r{round_num}_cell_{i}.png"
                    urllib.request.urlretrieve(cell_url, cell_path)
                    img_paths.append(cell_path)
                else:
                    img_paths.append("")
            except:
                img_paths.append("")

        log(f"Images ready: {len([p for p in img_paths if p])}/{len(cells)}")
        driver.switch_to.default_content()

        # Classify
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

        # Click cells with realistic delays
        driver.switch_to.frame(challenge_frame)
        cells = driver.find_elements(By.CSS_SELECTOR, ".task-image")
        for idx in clicks:
            if idx < len(cells):
                time.sleep(random.uniform(0.3, 0.8))
                driver.execute_script("arguments[0].click();", cells[idx])

        time.sleep(random.uniform(0.5, 1.0))

        # Click submit
        try:
            btn = driver.find_element(By.CSS_SELECTOR, ".button-submit")
            time.sleep(random.uniform(0.2, 0.5))
            driver.execute_script("arguments[0].click();", btn)
            log(f"Clicked submit: {btn.text}")
        except:
            pass

        driver.switch_to.default_content()
        time.sleep(random.uniform(3, 5))

        # Check if solved
        token = driver.execute_script("""
            var t = document.querySelector('textarea[name="h-captcha-response"]');
            return (t && t.value.length > 20) ? t.value : '';
        """)
        if token:
            log(f"Solved in round {round_num}! {len(token)} chars")
            return True

        log(f"Round {round_num} done, no token yet")
        time.sleep(random.uniform(1, 2))

    return False


def main():
    log("Starting UC browser with system Chrome...")
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,900")
    # Don't specify version_main or browser_executable_path — let UC use system Chrome

    driver = uc.Chrome(options=options)

    try:
        # Random mouse movements to build fingerprint
        log("Navigating to Receita...")
        driver.get(CPF_URL)
        time.sleep(random.uniform(2, 4))

        # Define recaptchaCallback before interacting
        driver.execute_script("""
            window.recaptchaCallback = function(token) {
                console.log('recaptchaCallback called with token: ' + token.length + ' chars');
                document.getElementById('idCheckedReCaptcha').value = 'true';
            };
        """)

        # Random scroll
        driver.execute_script("window.scrollTo(0, " + str(random.randint(50, 150)) + ");")
        time.sleep(random.uniform(0.5, 1))
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.5)

        # Fill CPF with human typing
        cpf_input = driver.find_element(By.ID, "txtCPF")
        actions = ActionChains(driver)
        actions.move_to_element(cpf_input).pause(random.uniform(0.1, 0.3)).click().perform()
        time.sleep(random.uniform(0.2, 0.5))
        human_type(driver, cpf_input, CPF)
        # Trigger blur
        driver.execute_script("document.getElementById('txtCPF').blur()")
        time.sleep(random.uniform(0.5, 1.0))

        # Fill date
        data_input = driver.find_element(By.ID, "txtDataNascimento")
        actions = ActionChains(driver)
        actions.move_to_element(data_input).pause(random.uniform(0.1, 0.3)).click().perform()
        time.sleep(random.uniform(0.2, 0.5))
        human_type(driver, data_input, DATA_NASC)
        driver.execute_script("document.getElementById('txtDataNascimento').blur()")
        time.sleep(random.uniform(0.5, 1.0))

        log(f"Form filled: CPF={cpf_input.get_attribute('value')}, Data={data_input.get_attribute('value')}")

        # Solve hCaptcha
        solved = solve_hcaptcha(driver)
        if not solved:
            log("FAILED to solve hCaptcha")
            return

        # Check form state after solving
        form_state = driver.execute_script("""
            return {
                cpf: document.getElementById('txtCPF').value,
                data: document.getElementById('txtDataNascimento').value,
                checked: document.getElementById('idCheckedReCaptcha').value,
                token_len: (document.querySelector('textarea[name="h-captcha-response"]') || {value:''}).value.length
            };
        """)
        log(f"Form state: {json.dumps(form_state)}")

        # Ensure idCheckedReCaptcha is true
        driver.execute_script("document.getElementById('idCheckedReCaptcha').value = 'true';")

        # CRITICAL: Add g-recaptcha-response and h-recaptcha-response fields
        # The server may expect these field names (from reCAPTCHA era)
        # hCaptcha with recaptchacompat=off only creates h-captcha-response
        driver.execute_script("""
            var token = document.querySelector('textarea[name="h-captcha-response"]').value;
            var form = document.getElementById('theForm');

            // Add g-recaptcha-response (reCAPTCHA v2 compat)
            var gField = document.createElement('textarea');
            gField.name = 'g-recaptcha-response';
            gField.value = token;
            gField.style.display = 'none';
            form.appendChild(gField);

            // Add h-recaptcha-response (what ValidarDados checks)
            var hField = document.createElement('textarea');
            hField.id = 'h-recaptcha-response';
            hField.name = 'h-recaptcha-response';
            hField.value = token;
            hField.style.display = 'none';
            form.appendChild(hField);

            console.log('Added compat fields, token length: ' + token.length);
        """)
        log("Added g-recaptcha-response and h-recaptcha-response compat fields")

        # Re-fill form if cleared
        cpf_val = form_state.get("cpf", "")
        data_val = form_state.get("data", "")
        if not cpf_val or len(cpf_val.replace(".", "").replace("-", "")) < 11:
            driver.execute_script(f"document.getElementById('txtCPF').value = '{CPF[:3]}.{CPF[3:6]}.{CPF[6:9]}-{CPF[9:]}';")
        if not data_val or len(data_val.replace("/", "")) < 8:
            driver.execute_script("document.getElementById('txtDataNascimento').value = '21/11/1958';")

        # Log all form fields being submitted
        form_data = driver.execute_script("""
            var form = document.getElementById('theForm');
            var data = {};
            var elements = form.querySelectorAll('input, textarea, select');
            elements.forEach(function(el) {
                if (el.name) data[el.name] = (el.value || '').substring(0, 100);
            });
            return data;
        """)
        log(f"Form POST data: {json.dumps(form_data)}")

        # Small random delay before submit
        time.sleep(random.uniform(0.5, 1.5))

        # Submit
        log("Submitting form...")
        submit_btn = driver.find_element(By.ID, "id_submit")
        actions = ActionChains(driver)
        actions.move_to_element(submit_btn).pause(random.uniform(0.1, 0.3)).click().perform()

        time.sleep(6)

        # Check result
        url = driver.current_url
        log(f"Result URL: {url}")

        if "Error=" in url:
            m = re.search(r'Error=(\d+)', url)
            log(f"ERROR: Receita returned Error={m.group(1) if m else '?'}")
            html = driver.page_source
            with open("/tmp/cpf_uc2_error.html", "w") as f:
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
            with open("/tmp/cpf_uc2_result.html", "w") as f:
                f.write(html)
            log("Result saved to /tmp/cpf_uc2_result.html")

    finally:
        driver.quit()
        log("Browser closed")


if __name__ == "__main__":
    main()

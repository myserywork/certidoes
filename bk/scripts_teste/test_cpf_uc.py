#!/usr/bin/env python3
"""Test CPF Receita using undetected-chromedriver + CLIP hCaptcha solver."""
import sys
import os
import time
import json
import tempfile
import re

sys.path.insert(0, "/root/pedro_project")
os.environ.setdefault("DISPLAY", ":121")

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

CPF_URL = "https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/consultapublica.asp"
CPF = "27290000625"
DATA_NASC = "21111958"


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[UC-CPF][{ts}] {msg}", flush=True)


def solve_hcaptcha_in_browser(driver):
    """Solve hCaptcha within the UC browser using CLIP."""
    from infra.hcaptcha_solver import classify_images_clip

    # Wait for hCaptcha iframe
    time.sleep(2)

    # Find and click the hCaptcha checkbox
    frames = driver.find_elements(By.TAG_NAME, "iframe")
    log(f"Found {len(frames)} iframes")

    checkbox_frame = None
    for frame in frames:
        src = frame.get_attribute("src") or ""
        if "hcaptcha" in src and "checkbox" in src:
            checkbox_frame = frame
            break
        if "newassets.hcaptcha.com" in src:
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

    driver.switch_to.frame(checkbox_frame)
    cb = driver.find_element(By.ID, "checkbox")
    cb.click()
    log("Clicked hCaptcha checkbox")
    driver.switch_to.default_content()

    time.sleep(5)

    # Check auto-solve
    token = driver.execute_script("""
        var t = document.querySelector('textarea[name="h-captcha-response"]');
        return (t && t.value.length > 20) ? t.value : '';
    """)
    if token:
        log(f"Auto-solved! {len(token)} chars")
        return True

    # Need to solve challenge rounds
    for round_num in range(1, 6):
        log(f"--- Round {round_num} ---")

        # Find challenge frame
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
            # Check if already solved
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

        # Get example image URL
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
                example_path = f"/tmp/uc_hcap_r{round_num}_example.png"
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
                    cell_path = f"/tmp/uc_hcap_r{round_num}_cell_{i}.png"
                    urllib.request.urlretrieve(cell_url, cell_path)
                    img_paths.append(cell_path)
                else:
                    img_paths.append("")
            except:
                img_paths.append("")

        log(f"Images ready: {len([p for p in img_paths if p])}/{len(cells)}")

        driver.switch_to.default_content()

        # Classify with CLIP
        clicks = classify_images_clip(prompt, img_paths, example_path)
        log(f"CLIP clicks: {clicks}")

        if not clicks:
            # Click skip
            driver.switch_to.frame(challenge_frame)
            try:
                btn = driver.find_element(By.CSS_SELECTOR, ".button-submit")
                btn.click()
            except:
                pass
            driver.switch_to.default_content()
            time.sleep(3)
            continue

        # Click cells via JavaScript (overlay div blocks native clicks)
        driver.switch_to.frame(challenge_frame)
        cells = driver.find_elements(By.CSS_SELECTOR, ".task-image")
        for idx in clicks:
            if idx < len(cells):
                driver.execute_script("arguments[0].click();", cells[idx])
                time.sleep(0.3)

        time.sleep(0.5)

        # Click submit via JavaScript
        try:
            btn = driver.find_element(By.CSS_SELECTOR, ".button-submit")
            driver.execute_script("arguments[0].click();", btn)
            log(f"Clicked submit: {btn.text}")
        except:
            pass

        driver.switch_to.default_content()
        time.sleep(4)

        # Check if solved
        token = driver.execute_script("""
            var t = document.querySelector('textarea[name="h-captcha-response"]');
            return (t && t.value.length > 20) ? t.value : '';
        """)
        if token:
            log(f"Solved in round {round_num}! {len(token)} chars")
            return True

        log(f"Round {round_num} done, no token yet")
        time.sleep(2)

    return False


def main():
    log("Starting UC browser...")
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1200,900")

    driver = uc.Chrome(
        options=options,
        version_main=131,
        browser_executable_path="/opt/chrome131/chrome",
    )

    try:
        log("Navigating to Receita...")
        driver.get(CPF_URL)
        time.sleep(3)

        # Fill CPF
        cpf_input = driver.find_element(By.ID, "txtCPF")
        cpf_input.click()
        cpf_input.clear()
        cpf_input.send_keys(CPF)
        # Trigger blur to format
        driver.execute_script("document.getElementById('txtCPF').blur()")
        time.sleep(0.5)

        # Fill date
        data_input = driver.find_element(By.ID, "txtDataNascimento")
        data_input.click()
        data_input.clear()
        data_input.send_keys(DATA_NASC)
        driver.execute_script("document.getElementById('txtDataNascimento').blur()")
        time.sleep(0.5)

        log(f"Form filled: CPF={cpf_input.get_attribute('value')}, Data={data_input.get_attribute('value')}")

        # Solve hCaptcha
        solved = solve_hcaptcha_in_browser(driver)
        if not solved:
            log("FAILED to solve hCaptcha")
            return

        # Verify form state
        form_state = driver.execute_script("""
            return {
                cpf: document.getElementById('txtCPF').value,
                data: document.getElementById('txtDataNascimento').value,
                checked: document.getElementById('idCheckedReCaptcha').value,
                token: (document.querySelector('textarea[name="h-captcha-response"]') || {}).value || ''
            };
        """)
        log(f"Form state before submit: {json.dumps(form_state)}")

        # Set idCheckedReCaptcha
        driver.execute_script("document.getElementById('idCheckedReCaptcha').value = 'true';")

        # Re-fill form if needed
        if not form_state.get("cpf"):
            driver.execute_script(f"document.getElementById('txtCPF').value = '{CPF[:3]}.{CPF[3:6]}.{CPF[6:9]}-{CPF[9:]}';")
        if not form_state.get("data"):
            driver.execute_script(f"document.getElementById('txtDataNascimento').value = '21/11/1958';")

        # Submit
        log("Submitting form...")
        driver.find_element(By.ID, "id_submit").click()

        time.sleep(5)

        # Check result
        url = driver.current_url
        log(f"Result URL: {url}")

        if "Error=" in url:
            m = re.search(r'Error=(\d+)', url)
            log(f"ERROR: Receita returned Error={m.group(1) if m else '?'}")
            # Save debug HTML
            html = driver.page_source
            with open("/tmp/cpf_uc_error.html", "w") as f:
                f.write(html)
            log("Debug HTML saved to /tmp/cpf_uc_error.html")
        else:
            html = driver.page_source
            log(f"Page length: {len(html)}")

            # Try to extract data
            nome_match = re.search(r'Nome.*?<[^>]*>([^<]+)', html)
            sit_match = re.search(r'Situa.*?Cadastral.*?<[^>]*>([^<]+)', html)

            if nome_match or sit_match:
                nome = nome_match.group(1).strip() if nome_match else ""
                situacao = sit_match.group(1).strip() if sit_match else ""
                log(f"SUCCESS! Nome: {nome}, Situacao: {situacao}")

            with open("/tmp/cpf_uc_result.html", "w") as f:
                f.write(html)
            log("Result HTML saved to /tmp/cpf_uc_result.html")

    finally:
        driver.quit()
        log("Browser closed")


if __name__ == "__main__":
    main()

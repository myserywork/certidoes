"""
Complete CPF Receita solver on Windows Chrome + WSL CLIP.
Windows Chrome = real browser (no webdriver flag, real GPU/display).
WSL = CLIP model for visual hCaptcha solving.
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
    print(f"[WIN][{ts}] {msg}", flush=True)


def classify_via_wsl(prompt, img_paths, example_path=""):
    """Call WSL CLIP classifier and return click indices."""
    # Convert Windows paths to WSL paths
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

    # Build Python command to run on WSL
    py_code = f'''
import sys, json
sys.path.insert(0, "/root/pedro_project")
from infra.hcaptcha_solver import classify_images_clip
prompt = {json.dumps(prompt)}
images = {json.dumps(wsl_paths)}
example = {json.dumps(wsl_example)}
clicks = classify_images_clip(prompt, images, example)
print(json.dumps(clicks))
'''

    try:
        result = subprocess.run(
            ["wsl", "-d", "Ubuntu-22.04", "-u", "root", "--", "python3", "-c", py_code],
            capture_output=True, text=True, timeout=60,
            cwd="C:\\Users\\workstation\\Desktop\\PEDRO_PROJECT\\PEDRO_PROJECT"
        )

        # Parse output - last line should be JSON
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.startswith("["):
                try:
                    return json.loads(line)
                except:
                    pass

        # Show all CLIP output
        for line in result.stderr.strip().split("\n"):
            line = line.strip()
            if line and ("cell" in line or "CLIP" in line or "HCAP" in line or "Identified" in line or "Related" in line or "Shelter" in line or "strategy" in line):
                log(f"  {line}")

        # Try parsing stdout
        if result.stdout.strip():
            try:
                return json.loads(result.stdout.strip().split("\n")[-1])
            except:
                log(f"WSL stdout: {result.stdout.strip()[-200:]}")

        return []
    except subprocess.TimeoutExpired:
        log("WSL CLIP timeout!")
        return []
    except Exception as e:
        log(f"WSL CLIP error: {e}")
        return []


def solve_hcaptcha(driver):
    """Solve hCaptcha visual challenge using CLIP on WSL."""
    time.sleep(2)

    # Find and click checkbox
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
        return False

    driver.switch_to.frame(checkbox_frame)
    cb = driver.find_element(By.ID, "checkbox")
    ActionChains(driver).move_to_element(cb).pause(0.2).click().perform()
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

    # Create temp dir for images
    os.makedirs(TEMP_DIR, exist_ok=True)

    # Solve challenge rounds
    for round_num in range(1, 9):
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
            token = driver.execute_script("""
                var t = document.querySelector('textarea[name="h-captcha-response"]');
                return (t && t.value.length > 20) ? t.value : '';
            """)
            if token:
                log(f"Solved!")
                return True
            log("No challenge frame found")
            return False

        driver.switch_to.frame(challenge_frame)

        # Get prompt
        try:
            prompt = driver.find_element(By.CSS_SELECTOR, ".prompt-text").text.strip()
        except:
            prompt = ""
        log(f"Prompt: '{prompt}'")

        # Get example image
        example_path = ""
        try:
            example_el = driver.find_element(By.CSS_SELECTOR, ".prompt-padding .image, .challenge-example .image")
            bg = driver.execute_script("return getComputedStyle(arguments[0]).backgroundImage", example_el)
            m = re.search(r'url\("?(.+?)"?\)', bg)
            if m:
                example_path = os.path.join(TEMP_DIR, f"r{round_num}_example.png")
                urllib.request.urlretrieve(m.group(1), example_path)
        except Exception as e:
            log(f"Example error: {e}")

        # Get cell images
        cells = driver.find_elements(By.CSS_SELECTOR, ".task-image")
        log(f"Cells: {len(cells)}")

        img_paths = []
        for i, cell in enumerate(cells):
            try:
                img_el = cell.find_element(By.CSS_SELECTOR, ".image")
                bg = driver.execute_script("return getComputedStyle(arguments[0]).backgroundImage", img_el)
                m = re.search(r'url\("?(.+?)"?\)', bg)
                if m:
                    path = os.path.join(TEMP_DIR, f"r{round_num}_cell_{i}.png")
                    urllib.request.urlretrieve(m.group(1), path)
                    img_paths.append(path)
                else:
                    img_paths.append("")
            except:
                img_paths.append("")

        log(f"Images: {len([p for p in img_paths if p])}/{len(cells)}")
        driver.switch_to.default_content()

        # Classify via WSL CLIP
        clicks = classify_via_wsl(prompt, img_paths, example_path)
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

        # Click cells
        driver.switch_to.frame(challenge_frame)
        cells = driver.find_elements(By.CSS_SELECTOR, ".task-image")
        for idx in clicks:
            if idx < len(cells):
                time.sleep(random.uniform(0.3, 0.8))
                driver.execute_script("arguments[0].click();", cells[idx])

        time.sleep(random.uniform(0.5, 1.0))

        # Submit
        try:
            btn = driver.find_element(By.CSS_SELECTOR, ".button-submit")
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

    return False


def main():
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{CDP_PORT}")

    log("Connecting to Chrome via CDP...")
    driver = webdriver.Chrome(options=chrome_options)
    log(f"Connected! navigator.webdriver={driver.execute_script('return navigator.webdriver')}")

    try:
        log("Navigating to Receita...")
        driver.get(CPF_URL)
        time.sleep(4)

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

        # Solve hCaptcha
        solved = solve_hcaptcha(driver)
        if not solved:
            log("FAILED to solve hCaptcha!")
            return

        # Prepare form
        driver.execute_script("""
            document.getElementById('idCheckedReCaptcha').value = 'true';

            // Add compat fields
            var token = document.querySelector('textarea[name="h-captcha-response"]').value;
            var form = document.getElementById('theForm');
            var f1 = document.createElement('input');
            f1.type = 'hidden'; f1.name = 'g-recaptcha-response'; f1.value = token;
            form.appendChild(f1);
            var f2 = document.createElement('input');
            f2.type = 'hidden'; f2.name = 'h-recaptcha-response'; f2.id = 'h-recaptcha-response'; f2.value = token;
            form.appendChild(f2);

            // Re-fill if needed
            var cpf = document.getElementById('txtCPF');
            var data = document.getElementById('txtDataNascimento');
            if (!cpf.value || cpf.value.replace(/\\D/g,'').length < 11) cpf.value = '272.900.006-25';
            if (!data.value || data.value.replace(/\\D/g,'').length < 8) data.value = '21/11/1958';
        """)

        time.sleep(random.uniform(0.5, 1.5))

        # Submit
        log("Submitting form...")
        submit = driver.find_element(By.ID, "id_submit")
        ActionChains(driver).move_to_element(submit).pause(0.2).click().perform()

        time.sleep(6)

        url = driver.current_url
        log(f"Result URL: {url}")

        if "Error=" in url:
            m = re.search(r'Error=(\d+)', url)
            log(f"ERROR: Error={m.group(1) if m else '?'}")
        else:
            html = driver.page_source
            log(f"Page length: {len(html)}")
            nome_match = re.search(r'Nome.*?<[^>]*>([^<]+)', html)
            sit_match = re.search(r'Situa.*?Cadastral.*?<[^>]*>([^<]+)', html)
            if nome_match or sit_match:
                nome = nome_match.group(1).strip() if nome_match else ""
                situacao = sit_match.group(1).strip() if sit_match else ""
                log(f"SUCCESS! Nome: {nome}, Situacao: {situacao}")

            with open(os.path.join(os.path.dirname(__file__), "cpf_win_result.html"), "w", encoding="utf-8") as f:
                f.write(html)
            log("Result saved!")

    finally:
        log("Done (browser stays open)")


if __name__ == "__main__":
    main()

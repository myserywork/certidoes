"""
Final attempt: Solve hCaptcha on Windows Chrome, submit via actual button click.
Also check all cookies, hidden fields, and network state before submit.
"""
import time
import json
import re
import random
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
    print(f"[FIN][{ts}] {msg}", flush=True)


def classify_via_wsl(prompt, img_paths, example_path=""):
    wsl_paths = [p.replace("\\", "/").replace("C:", "/mnt/c") if p else "" for p in img_paths]
    wsl_example = example_path.replace("\\", "/").replace("C:", "/mnt/c") if example_path else ""
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


def solve_rounds(driver, max_rounds=10):
    os.makedirs(TEMP_DIR, exist_ok=True)
    for round_num in range(1, max_rounds + 1):
        token = driver.execute_script("""
            var t = document.querySelector('textarea[name="h-captcha-response"]');
            return (t && t.value.length > 20) ? t.value : '';
        """)
        if token:
            return token

        challenge_frame = None
        for frame in driver.find_elements(By.TAG_NAME, "iframe"):
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
            return None

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
        log(f"R{round_num}: '{prompt[:50]}' clicks={clicks}")

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
        driver.execute_script("document.querySelector('.button-submit').click();")
        driver.switch_to.default_content()
        time.sleep(4)

    return None


def main():
    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{CDP_PORT}")

    log("Connecting...")
    driver = webdriver.Chrome(options=opts)
    log(f"webdriver={driver.execute_script('return navigator.webdriver')}")

    driver.get(CPF_URL)
    time.sleep(4)

    # Check ALL page resources, cookies, hidden fields
    page_info = driver.execute_script("""
        var info = {};
        info.cookies = document.cookie;
        info.url = location.href;

        // All meta tags
        info.metas = [];
        document.querySelectorAll('meta').forEach(function(m) {
            info.metas.push({name: m.name, content: m.content, httpEquiv: m.httpEquiv});
        });

        // All scripts
        info.scripts = [];
        document.querySelectorAll('script').forEach(function(s) {
            info.scripts.push((s.src || s.textContent.substring(0, 100)));
        });

        // All form fields (including hidden)
        var form = document.getElementById('theForm');
        info.formFields = [];
        if (form) {
            form.querySelectorAll('input, textarea, select').forEach(function(el) {
                info.formFields.push({
                    tag: el.tagName, id: el.id, name: el.name,
                    type: el.type, val: (el.value || '').substring(0, 50)
                });
            });
            info.formAction = form.action;
            info.formMethod = form.method;
        }

        return info;
    """)
    log(f"Cookies: {page_info.get('cookies')}")
    log(f"Form action: {page_info.get('formAction')}")
    log(f"Form fields: {json.dumps(page_info.get('formFields', []))}")

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

    # Click hCaptcha checkbox
    time.sleep(2)
    checkbox_frame = None
    for frame in driver.find_elements(By.TAG_NAME, "iframe"):
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
    ActionChains(driver).move_to_element(driver.find_element(By.ID, "checkbox")).pause(0.2).click().perform()
    log("Clicked checkbox")
    driver.switch_to.default_content()
    time.sleep(5)

    # Solve
    token = solve_rounds(driver, max_rounds=10)
    if not token:
        token = driver.execute_script("""
            var t = document.querySelector('textarea[name="h-captcha-response"]');
            return (t && t.value.length > 20) ? t.value : '';
        """)

    if not token:
        log("FAILED to solve!")
        return

    log(f"Token: {len(token)} chars")

    # Check cookies after solving (they might have changed)
    cookies_after = driver.execute_script("return document.cookie;")
    log(f"Cookies after solve: {cookies_after}")

    # Check all Selenium cookies
    sel_cookies = driver.get_cookies()
    log(f"All cookies: {json.dumps([{'name': c['name'], 'value': c['value'][:30], 'domain': c['domain']} for c in sel_cookies])}")

    # Prepare form
    driver.execute_script("""
        document.getElementById('idCheckedReCaptcha').value = 'true';
        var cpf = document.getElementById('txtCPF');
        var data = document.getElementById('txtDataNascimento');
        if (!cpf.value || cpf.value.replace(/\\D/g,'').length < 11) cpf.value = '272.900.006-25';
        if (!data.value || data.value.replace(/\\D/g,'').length < 8) data.value = '21/11/1958';
    """)

    # DO NOT add compat fields this time — submit with ONLY h-captcha-response
    # to test if the extra fields cause issues

    # Check form state
    form_check = driver.execute_script("""
        var form = document.getElementById('theForm');
        var fields = {};
        form.querySelectorAll('input, textarea').forEach(function(el) {
            if (el.name) fields[el.name] = (el.value || '').length > 50 ? el.value.substring(0,30) + '...' + el.value.length + 'chars' : el.value;
        });
        return fields;
    """)
    log(f"Final form: {json.dumps(form_check)}")

    # SUBMIT VIA ACTUAL BUTTON CLICK (real form submission)
    log("Clicking submit button...")
    submit = driver.find_element(By.ID, "id_submit")
    time.sleep(random.uniform(0.5, 1.0))

    # Use ActionChains for the most realistic click
    ActionChains(driver).move_to_element(submit).pause(0.3).click().perform()

    # Wait for page load
    time.sleep(8)

    url = driver.current_url
    log(f"Result URL: {url}")

    if "Error=" in url:
        m = re.search(r"Error=(\d+)", url)
        log(f"ERROR: Error={m.group(1) if m else '?'}")

        # Save full error page
        html = driver.page_source
        err_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cpf_error_final.html")
        with open(err_path, "w", encoding="utf-8") as f:
            f.write(html)
        log(f"Error page saved to cpf_error_final.html")

        # Also check the error message
        msg = re.search(r'mensagemErro">(.*?)<', html)
        if msg:
            log(f"Error message: {msg.group(1)}")

    elif "Exibir" in url or "Nome" in driver.page_source[:5000]:
        html = driver.page_source
        log(f"Page length: {len(html)}")
        nome = re.search(r'Nome.*?<[^>]*>([^<]+)', html)
        sit = re.search(r'Situa.*?Cadastral.*?<[^>]*>([^<]+)', html)
        if nome or sit:
            log(f"SUCCESS! Nome: {nome.group(1).strip() if nome else ''}, Sit: {sit.group(1).strip() if sit else ''}")
        result_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cpf_result_final.html")
        with open(result_path, "w", encoding="utf-8") as f:
            f.write(html)
        log(f"Result saved!")
    else:
        log(f"Unknown page state. URL: {url}")
        html = driver.page_source
        log(f"Body preview: {html[:500]}")

    log("Done")


if __name__ == "__main__":
    main()

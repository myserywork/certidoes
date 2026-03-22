#!/usr/bin/env python3
"""
Test CPF Receita — solve hCaptcha via direct API interaction + CLIP.
Bypasses browser fingerprinting entirely by mimicking hCaptcha's JS widget API calls.
"""
import sys
import os
import time
import json
import re
import random
import hashlib
import base64

sys.path.insert(0, "/root/pedro_project")

import requests
from urllib.parse import urlencode

CPF_URL = "https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/consultapublica.asp"
SUBMIT_URL = "https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/ConsultaPublicaExibir.asp"
SITEKEY = "53be2ee7-5efc-494e-a3ba-c9258649c070"
HOST = "servicos.receita.fazenda.gov.br"
CPF = "27290000625"
DATA_NASC = "21/11/1958"
CPF_FMT = "272.900.006-25"

HCAPTCHA_API = "https://api2.hcaptcha.com"
HCAPTCHA_ASSETS = "https://newassets.hcaptcha.com"


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[API][{ts}] {msg}", flush=True)


def get_motion_data():
    """Generate realistic-looking motion data."""
    import time as _t
    now = int(_t.time() * 1000)
    st = now - random.randint(3000, 8000)

    # Simulate mouse movements
    mm = []
    x, y = random.randint(200, 600), random.randint(200, 400)
    for i in range(random.randint(10, 25)):
        x += random.randint(-30, 30)
        y += random.randint(-20, 20)
        t = st + i * random.randint(50, 200)
        mm.append({"x": max(0, x), "y": max(0, y), "t": t})

    # Simulate mouse downs/ups
    md = [{"x": mm[-1]["x"], "y": mm[-1]["y"], "t": mm[-1]["t"] + 50}]
    mu = [{"x": mm[-1]["x"], "y": mm[-1]["y"], "t": mm[-1]["t"] + 150}]

    return {
        "v": 1,
        "topLevel": {
            "st": st,
            "sc": {"availWidth": 1280, "availHeight": 900, "width": 1280, "height": 900,
                   "colorDepth": 24, "pixelDepth": 24, "availLeft": 0, "availTop": 0},
            "nv": {
                "vendorSub": "", "productSub": "20030107",
                "vendor": "Google Inc.", "maxTouchPoints": 0,
                "userActivation": {}, "doNotTrack": None,
                "hardwareConcurrency": 8, "cookieEnabled": True,
                "appCodeName": "Mozilla", "appName": "Netscape",
                "appVersion": "5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
                "platform": "Linux x86_64",
                "userAgent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
                "language": "pt-BR", "languages": ["pt-BR", "pt", "en-US", "en"],
                "onLine": True, "webdriver": False,
                "pdfViewerEnabled": True, "deviceMemory": 8,
            },
            "dr": "",
            "inv": False,
            "exec": False,
        },
        "session": [],
        "widgetList": [SITEKEY],
        "widgetId": SITEKEY,
        "href": CPF_URL,
        "prev": {
            "escaped": False,
            "passed": False,
            "expiredChallenge": False,
            "expiredResponse": False,
        },
    }


def solve_pow(req_data):
    """Solve proof-of-work challenge from hCaptcha."""
    pow_type = req_data.get("type", "")
    if pow_type == "hsw":
        # HSW (HCaptcha Solver Worker) PoW
        # This requires a WASM worker - skip for now
        return ""
    elif pow_type == "hsl":
        # HSL (HCaptcha Solver Light) PoW
        data = req_data.get("req", "")
        # Simple HSL solver
        return ""
    return ""


def main():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    # Step 1: Load the Receita page to get ASP session cookie
    log("Loading Receita page...")
    resp = session.get(CPF_URL)
    log(f"Page loaded: {resp.status_code}, cookies: {dict(session.cookies)}")

    # Step 2: Check hCaptcha site config
    log("Checking hCaptcha site config...")
    config_url = f"{HCAPTCHA_API}/checksiteconfig"
    config_params = {
        "v": "5ea3feff",
        "host": HOST,
        "sitekey": SITEKEY,
        "sc": "1",
        "swa": "1",
        "spst": "1",
    }
    config_resp = session.get(config_url, params=config_params)
    log(f"Site config: {config_resp.status_code}")
    try:
        config_data = config_resp.json()
        log(f"Config: {json.dumps(config_data)[:500]}")
    except:
        log(f"Config response: {config_resp.text[:500]}")
        config_data = {}

    # Step 3: Get captcha challenge
    log("Getting captcha challenge...")
    motion_data = get_motion_data()

    getcaptcha_url = f"{HCAPTCHA_API}/getcaptcha/{SITEKEY}"
    getcaptcha_data = {
        "v": "5ea3feff",
        "sitekey": SITEKEY,
        "host": HOST,
        "hl": "pt-BR",
        "motionData": json.dumps(motion_data),
        "pdc": json.dumps({"s": int(time.time() * 1000), "n": 0, "p": 0, "gcs": random.randint(50, 200)}),
        "n": "",  # PoW answer
        "c": json.dumps(config_data.get("c", {})),  # PoW config
    }

    captcha_resp = session.post(
        getcaptcha_url,
        data=getcaptcha_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://newassets.hcaptcha.com",
            "Referer": "https://newassets.hcaptcha.com/",
        }
    )
    log(f"GetCaptcha: {captcha_resp.status_code}")
    try:
        captcha_data = captcha_resp.json()
        log(f"Captcha response keys: {list(captcha_data.keys())}")
        log(f"Captcha data: {json.dumps(captcha_data)[:1000]}")
    except:
        log(f"Captcha response: {captcha_resp.text[:500]}")
        return

    # Check if we need PoW
    if captcha_data.get("pass"):
        log(f"Auto-passed! Token: {captcha_data.get('generated_pass_UUID', '')[:50]}")
        token = captcha_data.get("generated_pass_UUID", "")
    elif "tasklist" in captcha_data:
        # Challenge mode
        challenge_key = captcha_data.get("key", "")
        request_type = captcha_data.get("request_type", "")
        tasklist = captcha_data.get("tasklist", [])
        log(f"Challenge: key={challenge_key[:30]}..., type={request_type}, tasks={len(tasklist)}")

        if tasklist:
            # Get prompt from requester_question
            prompt_data = captcha_data.get("requester_question", {})
            prompt = prompt_data.get("pt-BR", prompt_data.get("en", ""))
            log(f"Prompt: '{prompt}'")

            # Get example image
            example_url = ""
            example_data = captcha_data.get("requester_question_example", [])
            if example_data:
                example_url = example_data[0] if isinstance(example_data, list) else example_data
                log(f"Example: {example_url[:80]}")

            # Download and classify images
            from infra.hcaptcha_solver import classify_images_clip
            import urllib.request

            img_paths = []
            for i, task in enumerate(tasklist):
                task_url = task.get("datapoint_uri", "") if isinstance(task, dict) else task
                if task_url:
                    path = f"/tmp/api_cell_{i}.png"
                    try:
                        urllib.request.urlretrieve(task_url, path)
                        img_paths.append(path)
                    except:
                        img_paths.append("")
                else:
                    img_paths.append("")

            example_path = ""
            if example_url:
                example_path = "/tmp/api_example.png"
                try:
                    urllib.request.urlretrieve(example_url, example_path)
                except:
                    example_path = ""

            log(f"Downloaded {len([p for p in img_paths if p])}/{len(tasklist)} images")

            clicks = classify_images_clip(prompt, img_paths, example_path)
            log(f"CLIP clicks: {clicks}")

            # Build answers
            answers = {}
            for i, task in enumerate(tasklist):
                task_key = task.get("task_key", "") if isinstance(task, dict) else str(i)
                answers[task_key] = "true" if i in clicks else "false"

            # Submit answers
            check_url = f"{HCAPTCHA_API}/checkcaptcha/{SITEKEY}/{challenge_key}"
            check_data = {
                "v": "5ea3feff",
                "job_mode": request_type,
                "answers": answers,
                "serverdomain": HOST,
                "sitekey": SITEKEY,
                "motionData": json.dumps(get_motion_data()),
                "n": "",
                "c": json.dumps(config_data.get("c", {})),
            }

            check_resp = session.post(
                check_url,
                json=check_data,
                headers={
                    "Content-Type": "application/json",
                    "Origin": "https://newassets.hcaptcha.com",
                    "Referer": "https://newassets.hcaptcha.com/",
                }
            )
            log(f"CheckCaptcha: {check_resp.status_code}")
            try:
                check_result = check_resp.json()
                log(f"Check result: {json.dumps(check_result)[:500]}")
                if check_result.get("pass"):
                    token = check_result.get("generated_pass_UUID", "")
                    log(f"SOLVED! Token: {len(token)} chars")
                else:
                    log("Challenge failed")
                    return
            except:
                log(f"Check response: {check_resp.text[:300]}")
                return
        else:
            log("No tasklist in challenge")
            return
    else:
        log(f"Unexpected response: {json.dumps(captcha_data)[:500]}")
        return

    if not token:
        log("No token obtained")
        return

    # Step 4: Submit the form with the hCaptcha token
    log(f"Submitting form with token ({len(token)} chars)...")
    submit_data = {
        "idCheckedReCaptcha": "true",
        "txtCPF": CPF_FMT,
        "txtDataNascimento": DATA_NASC,
        "h-captcha-response": token,
        "Enviar": "Consultar",
    }

    submit_resp = session.post(
        SUBMIT_URL,
        data=submit_data,
        headers={
            "Referer": CPF_URL,
            "Origin": "https://servicos.receita.fazenda.gov.br",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        allow_redirects=True,
    )

    log(f"Submit: {submit_resp.status_code}, URL: {submit_resp.url}")

    if "Error=" in submit_resp.url:
        m = re.search(r'Error=(\d+)', submit_resp.url)
        log(f"ERROR: Error={m.group(1) if m else '?'}")
        with open("/tmp/cpf_api_error.html", "w") as f:
            f.write(submit_resp.text)
    else:
        html = submit_resp.text
        log(f"Page length: {len(html)}")
        nome_match = re.search(r'Nome.*?<[^>]*>([^<]+)', html)
        sit_match = re.search(r'Situa.*?Cadastral.*?<[^>]*>([^<]+)', html)
        if nome_match or sit_match:
            nome = nome_match.group(1).strip() if nome_match else ""
            situacao = sit_match.group(1).strip() if sit_match else ""
            log(f"SUCCESS! Nome: {nome}, Situacao: {situacao}")
        with open("/tmp/cpf_api_result.html", "w") as f:
            f.write(html)
        log("Result saved")


if __name__ == "__main__":
    main()

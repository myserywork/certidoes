"""
2Captcha Solver — resolve CAPTCHAs via API do 2captcha.com

Suporta:
  - reCAPTCHA v2 (TCU, MPGO)
  - reCAPTCHA Enterprise (IBAMA, STF)
  - hCaptcha (CPF Receita)
  - Turnstile (MPF - backup)

Uso:
    from infra.twocaptcha_solver import solve_recaptcha_v2, solve_recaptcha_enterprise, solve_hcaptcha

    token = solve_recaptcha_v2(sitekey, url)
    token = solve_recaptcha_enterprise(sitekey, url, action="submit")
    token = solve_hcaptcha(sitekey, url)
"""
import os
import time
import requests

API_KEY = os.environ.get("CAPTCHA_API_KEY", os.environ.get("API_KEY_2CAPTCHA", ""))
SUBMIT_URL = "http://2captcha.com/in.php"
RESULT_URL = "http://2captcha.com/res.php"
MAX_WAIT = 120  # segundos
POLL_INTERVAL = 5


def _submit(params: dict) -> str:
    """Envia captcha e retorna captcha_id."""
    params["key"] = API_KEY
    params["json"] = 1

    resp = requests.post(SUBMIT_URL, data=params, timeout=30)

    # Tentar JSON primeiro, fallback para texto
    try:
        data = resp.json()
        if data.get("status") != 1:
            raise Exception(f"2captcha submit erro: {data.get('request', data)}")
        return data["request"]
    except (ValueError, KeyError):
        # Formato texto: "OK|captcha_id"
        text = resp.text.strip()
        if text.startswith("OK|"):
            return text.split("|")[1]
        raise Exception(f"2captcha submit erro: {text}")


def _poll(captcha_id: str) -> str:
    """Aguarda resolucao e retorna token."""
    for _ in range(MAX_WAIT // POLL_INTERVAL):
        time.sleep(POLL_INTERVAL)

        resp = requests.get(RESULT_URL, params={
            "key": API_KEY,
            "action": "get",
            "id": captcha_id,
            "json": 1,
        }, timeout=30)

        text = resp.text.strip()
        # Tentar JSON
        try:
            data = resp.json()
            if data.get("status") == 1:
                return data["request"]
            if data.get("request") != "CAPCHA_NOT_READY":
                raise Exception(f"2captcha erro: {data.get('request', data)}")
        except (ValueError, KeyError):
            # Formato texto
            if text.startswith("OK|"):
                return text.split("|", 1)[1]
            if "CAPCHA_NOT_READY" in text:
                continue
            raise Exception(f"2captcha erro: {text}")

    raise Exception("2captcha timeout")


def _check_key():
    if not API_KEY:
        raise Exception("CAPTCHA_API_KEY nao configurada. Defina no .env")


# ─── reCAPTCHA v2 ─────────────────────────────────────────

def solve_recaptcha_v2(sitekey: str, url: str) -> str:
    """Resolve reCAPTCHA v2 (checkbox/invisible). Usado em TCU, MPGO."""
    _check_key()
    captcha_id = _submit({
        "method": "userrecaptcha",
        "googlekey": sitekey,
        "pageurl": url,
    })
    return _poll(captcha_id)


# ─── reCAPTCHA Enterprise ─────────────────────────────────

def solve_recaptcha_enterprise(sitekey: str, url: str, action: str = "submit") -> str:
    """Resolve reCAPTCHA Enterprise (invisible/score). Usado em IBAMA, STF."""
    _check_key()
    captcha_id = _submit({
        "method": "userrecaptcha",
        "googlekey": sitekey,
        "pageurl": url,
        "enterprise": 1,
        "action": action,
    })
    return _poll(captcha_id)


# ─── hCaptcha ─────────────────────────────────────────────

def solve_hcaptcha(sitekey: str, url: str) -> str:
    """Resolve hCaptcha. Usado em CPF Receita."""
    _check_key()
    captcha_id = _submit({
        "method": "hcaptcha",
        "sitekey": sitekey,
        "pageurl": url,
    })
    return _poll(captcha_id)


# ─── Turnstile ────────────────────────────────────────────

def solve_turnstile(sitekey: str, url: str) -> str:
    """Resolve Cloudflare Turnstile. Backup para MPF."""
    _check_key()
    captcha_id = _submit({
        "method": "turnstile",
        "sitekey": sitekey,
        "pageurl": url,
    })
    return _poll(captcha_id)

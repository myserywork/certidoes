#!/usr/bin/env python3
"""
Módulo reCAPTCHA Solver via HTTP puro (sem browser).

FUNCIONA PARA:
  - reCAPTCHA v2 invisible
  - reCAPTCHA v3
  - reCAPTCHA Enterprise invisible

NÃO FUNCIONA PARA:
  - reCAPTCHA v2 normal (checkbox) → Google exige interação real

Uso:
    from recaptcha_solver import resolver_recaptcha, resolver_por_sitekey

    # Se já tem anchor URL completa:
    token = resolver_recaptcha(anchor_url)

    # Se só tem sitekey + domínio:
    token = resolver_por_sitekey(sitekey, dominio)
"""
import re
import requests
import urllib.parse
import base64


def _extrair_parametros_anchor(anchor_url):
    parsed = urllib.parse.urlparse(anchor_url)
    params = urllib.parse.parse_qs(parsed.query)
    return {
        'k': params.get('k', [''])[0],
        'v': params.get('v', [''])[0],
        'co': params.get('co', [''])[0],
        'hl': params.get('hl', ['en'])[0],
        'size': params.get('size', ['invisible'])[0],
    }


def resolver_recaptcha(anchor_url, proxy=None, timeout=15):
    """
    Resolve reCAPTCHA dado anchor URL completa.
    Retorna token string ou None.
    """
    params = _extrair_parametros_anchor(anchor_url)
    k = params['k']
    v = params['v']
    co = params['co']
    hl = params['hl']
    size = params['size']

    if not k:
        return None

    s = requests.Session()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}

    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # 1. GET anchor → extrair recaptcha-token
    r1 = s.get(anchor_url, headers=h, timeout=timeout)
    m = re.search(r'id="recaptcha-token" value="([^"]+)"', r1.text)
    if not m:
        return None
    tok = m.group(1)

    # 2. POST reload → extrair token final
    h["Content-Type"] = "application/x-www-form-urlencoded"

    # Tentar combinações: enterprise + api2, reasons q/fi/a
    for endpoint in ['enterprise', 'api2']:
        for reason in ['q', 'fi', 'a']:
            url = f"https://www.google.com/recaptcha/{endpoint}/reload?k={k}"
            payload = f"v={v}&reason={reason}&c={tok}&k={k}&co={co}&hl={hl}&size={size}"
            r2 = s.post(url, headers=h, data=payload, timeout=timeout)

            mx = re.search(r'\["rresp","([^"]+)"', r2.text)
            if mx and len(mx.group(1)) > 50:
                return mx.group(1)

    return None


def resolver_por_sitekey(sitekey, dominio, size="invisible", proxy=None, timeout=15):
    """
    Resolve reCAPTCHA dado sitekey e domínio.
    Constrói anchor URL automaticamente.
    """
    # Codificar domínio em base64 (formato co)
    co = base64.b64encode(f"https://{dominio}:443".encode()).decode().rstrip("=")

    # Buscar versão do recaptcha
    s = requests.Session()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}

    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # Pegar versão do api.js
    r = s.get("https://www.google.com/recaptcha/api.js", headers=h, timeout=timeout)
    v_match = re.search(r'releases/([a-zA-Z0-9_-]+)/', r.text)
    version = v_match.group(1) if v_match else "P8cyHPrXODVy7ASorEhMUv3P"

    anchor_url = (
        f"https://www.google.com/recaptcha/api2/anchor?ar=1&k={sitekey}"
        f"&co={co}&hl=pt-BR&v={version}&size={size}"
        f"&anchor-ms=20000&execute-ms=30000&cb=solver"
    )

    return resolver_recaptcha(anchor_url, proxy=proxy, timeout=timeout)


# ─── CLI ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import argparse

    p = argparse.ArgumentParser(description="reCAPTCHA solver HTTP")
    p.add_argument("--anchor", help="Anchor URL completa")
    p.add_argument("--sitekey", help="Site key")
    p.add_argument("--domain", help="Domínio do site (ex: cadunico.dataprev.gov.br)")
    p.add_argument("--size", default="invisible", help="invisible|normal")
    p.add_argument("--proxy", help="Proxy URL")
    a = p.parse_args()

    token = None
    if a.anchor:
        token = resolver_recaptcha(a.anchor, proxy=a.proxy)
    elif a.sitekey and a.domain:
        token = resolver_por_sitekey(a.sitekey, a.domain, size=a.size, proxy=a.proxy)
    else:
        print("Use --anchor URL ou --sitekey KEY --domain DOMAIN")
        sys.exit(1)

    if token:
        print(f"TOKEN ({len(token)} chars):")
        print(token)
    else:
        print("FALHA")
        sys.exit(1)

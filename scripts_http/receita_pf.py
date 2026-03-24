"""Receita Federal PF — 100% HTTP (sem browser)"""
import os
import sys
import json
import time
import requests
from pathlib import Path
from scripts_http._shared import clean_certidao_html, html_to_pdf, upload_pdf

TITULO = "Certidao Receita Federal PF"
ORGAO = "Receita Federal do Brasil"
API_BASE = "https://servicos.receitafederal.gov.br/servico/certidoes/api"
CAPTCHA_KEY = os.environ.get("CAPTCHA_API_KEY", "")
HCAPTCHA_SITEKEY = "4a65992d-58fc-4812-8b87-789f7e7c4c4b"
PAGE_URL = "https://servicos.receitafederal.gov.br/servico/certidoes/"

import time


def solve_hcaptcha() -> str:
    """Resolve hCaptcha via 2captcha (usa solver compartilhado)."""
    if not CAPTCHA_KEY:
        return ""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from infra.twocaptcha_solver import solve_hcaptcha as _solve
        token = _solve(HCAPTCHA_SITEKEY, PAGE_URL)
        if token:
            print("[Receita PF] hCaptcha resolvido via 2captcha!")
        return token or ""
    except Exception as e:
        print(f"[Receita PF] 2captcha falhou: {e}")
        return ""


def emitir_certidao_receita_pf(cpf: str, dt_nascimento: str) -> dict:
    """Emite certidao PF 100% via HTTP."""
    print(f"[Receita PF] HTTP para CPF: {cpf}")
    clean_cpf = cpf.replace(".", "").replace("-", "").replace(" ", "")

    # Converter DD/MM/AAAA para AAAA-MM-DD
    parts = dt_nascimento.replace("-", "/").split("/")
    if len(parts) == 3:
        if len(parts[0]) == 4:  # AAAA-MM-DD
            dt_iso = f"{parts[0]}-{parts[1]}-{parts[2]}"
        else:  # DD/MM/AAAA
            dt_iso = f"{parts[2]}-{parts[1]}-{parts[0]}"
    else:
        return {"status": "erro", "mensagem": f"Data invalida: {dt_nascimento}"}

    print(f"[Receita PF] Data ISO: {dt_iso}")

    # 1. Resolver hCaptcha
    print("[Receita PF] Resolvendo hCaptcha...")
    captcha_token = solve_hcaptcha()
    if not captcha_token:
        return {"status": "erro", "mensagem": "hCaptcha nao resolvido (sem CAPTCHA_API_KEY?)"}

    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": "https://servicos.receitafederal.gov.br",
        "Referer": PAGE_URL,
    })
    # Enviar captcha token como cookie E header (a Receita pode checar em qualquer lugar)
    session.cookies.set("h-captcha-response", captcha_token, domain="servicos.receitafederal.gov.br")
    session.cookies.set("captchaResponse", captcha_token, domain="servicos.receitafederal.gov.br")

    try:
        # 2. Pegar sessao/cookies visitando a pagina primeiro
        print("[Receita PF] Obtendo sessao...")
        session.get(PAGE_URL, timeout=15)
        session.get(f"{API_BASE}/env", timeout=10)

        # 3. Verificar/Emitir certidao
        print("[Receita PF] Chamando API Emissao/verificar...")
        r = session.post(f"{API_BASE}/Emissao/verificar", json={
            "ni": clean_cpf,
            "tipoContribuinte": "PF",
            "dataNascimento": dt_iso,
            "tipoContribuinteEnum": "CPF",
            "captchaResponse": captcha_token,
            "hCaptchaResponse": captcha_token,
        }, timeout=30)

        print(f"[Receita PF] Response: {r.status_code} ({len(r.text)} bytes)")
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}

        status_validacao = data.get("statusValidacao", "")
        print(f"[Receita PF] Status: {status_validacao}")

        if status_validacao == "CaptchaTokenNaoInformado":
            return {"status": "erro", "mensagem": "Captcha nao aceito pela Receita"}

        if status_validacao == "Erro":
            msg = data.get("mensagem", data.get("message", "Erro desconhecido"))
            return {"status": "falha", "mensagem": f"Receita: {msg}"}

        # 3. Se tem certidao, tentar pegar PDF
        if "certidao" in str(data).lower() or status_validacao in ("CertidaoEmitida", "CertidaoExistente", "Sucesso", ""):
            # Tentar endpoint de emissao
            r2 = session.post(f"{API_BASE}/Emissao/emitir", json={
                "ni": clean_cpf,
                "tipoContribuinte": "PF",
                "dataNascimento": dt_iso,
                "tipoContribuinteEnum": "CPF",
            }, timeout=30)

            print(f"[Receita PF] Emitir: {r2.status_code} ({len(r2.content)} bytes)")

            # Se retornou PDF
            content_type = r2.headers.get("content-type", "")
            if "pdf" in content_type or (r2.content[:5] == b'%PDF-'):
                import tempfile
                tmpdir = tempfile.mkdtemp()
                pdf_path = os.path.join(tmpdir, f"certidao_receita_pf_{clean_cpf}.pdf")
                with open(pdf_path, "wb") as f:
                    f.write(r2.content)
                print(f"[Receita PF] PDF direto: {len(r2.content)} bytes")
                link = upload_pdf(pdf_path)
                return {"status": "sucesso", "link": link, "tipo_certidao": "receita_pf", "mensagem": "Certidao emitida"}

            # Se retornou HTML/JSON com dados da certidao
            if r2.text and len(r2.text) > 200:
                data2 = r2.json() if "json" in content_type else {}
                # Gerar PDF do resultado
                html = f"<h1>Certidao de Regularidade Fiscal - CPF {clean_cpf}</h1><pre>{json.dumps(data2 or data, indent=2, ensure_ascii=False)}</pre>"
                cleaned = clean_certidao_html(html, TITULO, ORGAO)
                pdf_path = html_to_pdf(cleaned, f"certidao_receita_pf_{clean_cpf}.pdf")
                if pdf_path:
                    link = upload_pdf(pdf_path)
                    return {"status": "sucesso", "link": link, "tipo_certidao": "receita_pf", "mensagem": "Certidao emitida (HTML)"}

        # Resposta nao reconhecida
        return {"status": "falha", "mensagem": f"Receita retornou: {status_validacao or r.text[:100]}"}

    except Exception as e:
        print(f"[Receita PF] Erro: {e}")
        return {"status": "erro", "mensagem": str(e)[:200]}

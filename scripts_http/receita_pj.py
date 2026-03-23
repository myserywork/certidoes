"""
Receita Federal - Certidao Pessoa Juridica (HTTP-only, sem browser)

NOTA: Este script tenta acessar a API da Receita Federal para emissao de
certidoes de regularidade fiscal (CNPJ). A Receita usa um app Angular em
https://solucoes.receita.fazenda.gov.br/Servicos/certidaointernet/PJ/Emitir
que faz chamadas a APIs internas. Os endpoints abaixo sao best-guess e
podem precisar de ajuste apos inspecao via DevTools.

Endpoints conhecidos:
- GET  .../PJ/Emitir → pagina inicial (obtem cookies)
- POST .../PJ/Validar → valida CNPJ e retorna token/captcha
- POST .../PJ/Certidao → emite a certidao (retorna PDF direto ou HTML)
"""

import subprocess
import tempfile
import os
import re
import time
import requests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def html_to_pdf(html_content: str, filename: str = "certidao.pdf") -> str:
    """Convert HTML to PDF using Chrome headless --print-to-pdf."""
    tmpdir = tempfile.mkdtemp()
    html_path = os.path.join(tmpdir, "page.html")
    pdf_path = os.path.join(tmpdir, filename)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not os.path.exists(chrome):
        chrome = "google-chrome"

    subprocess.run([
        chrome, "--headless", "--disable-gpu", "--no-sandbox",
        f"--print-to-pdf={pdf_path}", f"file:///{html_path.replace(os.sep, '/')}"
    ], capture_output=True, timeout=30)

    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 100:
        return pdf_path
    return None


def upload_pdf(pdf_path: str) -> str:
    """Upload PDF to tmpfiles.org."""
    with open(pdf_path, "rb") as f:
        r = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": f}, timeout=30)
    if r.status_code == 200:
        data = r.json()
        return data.get("data", {}).get("url", "")
    return None


def save_bytes_as_pdf(content: bytes, filename: str = "certidao.pdf") -> str:
    """Salva bytes (PDF binario) em arquivo temporario."""
    tmpdir = tempfile.mkdtemp()
    pdf_path = os.path.join(tmpdir, filename)
    with open(pdf_path, "wb") as f:
        f.write(content)
    if os.path.getsize(pdf_path) > 100:
        return pdf_path
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def emitir_certidao_receita_pj(cnpj: str) -> dict:
    """Emite certidao de regularidade fiscal da Receita Federal (CNPJ).

    IMPORTANTE: A Receita Federal pode exigir captcha ou certificado digital.
    Este script tenta o fluxo mais simples (sem captcha). Se falhar, pode ser
    necessario usar o solver de captcha ou o script Selenium como fallback.

    Args:
        cnpj: CNPJ (somente digitos, 14 caracteres).
    """
    print(f"[Receita PJ] Iniciando para CNPJ: {cnpj}")

    # Limpar CNPJ
    cnpj_limpo = re.sub(r"\D", "", cnpj)

    base_url = "https://solucoes.receita.fazenda.gov.br/Servicos/certidaointernet/PJ"

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    try:
        # 1) GET pagina inicial - obter cookies e tokens
        print("[Receita PJ] Obtendo pagina inicial...")
        r1 = session.get(f"{base_url}/Emitir", timeout=30, verify=True)
        r1.raise_for_status()
        print(f"[Receita PJ] Pagina obtida (status {r1.status_code})")

        # Tentar extrair __RequestVerificationToken (ASP.NET MVC anti-forgery)
        token = None
        m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', r1.text)
        if m:
            token = m.group(1)
            print("[Receita PJ] Token anti-forgery extraido.")

        # 2) POST para validar/emitir
        # NOTA: O endpoint exato pode variar. Tentamos o fluxo direto.
        print("[Receita PJ] Tentando emitir certidao...")
        payload = {
            "NI": cnpj_limpo,
        }
        if token:
            payload["__RequestVerificationToken"] = token

        headers_post = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"{base_url}/Emitir",
            "Origin": "https://solucoes.receita.fazenda.gov.br",
        }

        r2 = session.post(
            f"{base_url}/Emitir",
            data=payload,
            timeout=60,
            verify=True,
            headers=headers_post,
        )
        r2.raise_for_status()
        print(f"[Receita PJ] Resposta recebida ({len(r2.content)} bytes, content-type: {r2.headers.get('Content-Type', 'N/A')})")

        # A Receita pode retornar:
        # a) PDF binario (application/pdf)
        # b) HTML com a certidao
        # c) HTML com erro/captcha

        content_type = r2.headers.get("Content-Type", "")

        if "application/pdf" in content_type:
            # PDF direto
            print("[Receita PJ] Resposta eh PDF direto.")
            pdf_path = save_bytes_as_pdf(r2.content, "certidao_receita_pj.pdf")
        elif len(r2.text) > 500:
            # HTML - converter para PDF
            if "captcha" in r2.text.lower() or "recaptcha" in r2.text.lower():
                return {
                    "status": "erro",
                    "link": None,
                    "mensagem": "Receita Federal exige captcha. Use o script Selenium como fallback.",
                }
            print("[Receita PJ] Convertendo HTML para PDF...")
            pdf_path = html_to_pdf(r2.text, "certidao_receita_pj.pdf")
        else:
            return {
                "status": "erro",
                "link": None,
                "mensagem": f"Resposta inesperada ({len(r2.text)} bytes). Possivel bloqueio ou captcha.",
            }

        if not pdf_path:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Falha ao gerar/salvar PDF.",
            }

        # 3) Upload
        print("[Receita PJ] Fazendo upload do PDF...")
        link = upload_pdf(pdf_path)
        if not link:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Falha no upload do PDF.",
            }

        print(f"[Receita PJ] Sucesso! Link: {link}")
        return {
            "status": "sucesso",
            "link": link,
            "mensagem": "Certidao Receita Federal PJ emitida com sucesso.",
        }

    except requests.exceptions.RequestException as e:
        print(f"[Receita PJ] Erro de rede: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro de rede: {e}",
        }
    except Exception as e:
        print(f"[Receita PJ] Erro inesperado: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro inesperado: {e}",
        }


if __name__ == "__main__":
    import sys
    cnpj = sys.argv[1] if len(sys.argv) > 1 else "00000000000100"
    result = emitir_certidao_receita_pj(cnpj)
    print(result)

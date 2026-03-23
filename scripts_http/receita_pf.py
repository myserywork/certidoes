"""
Receita Federal - Certidao Pessoa Fisica (HTTP-only, sem browser)

NOTA: A Receita usa um app em
https://solucoes.receita.fazenda.gov.br/Servicos/certidaointernet/PF/Emitir
Os endpoints abaixo sao best-guess e podem precisar de ajuste apos inspecao
via DevTools. A Receita pode exigir captcha.

Endpoints conhecidos:
- GET  .../PF/Emitir → pagina inicial (obtem cookies)
- POST .../PF/Emitir → submete CPF + data nascimento
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

def emitir_certidao_receita_pf(cpf: str, dt_nascimento: str) -> dict:
    """Emite certidao de regularidade fiscal da Receita Federal (CPF).

    IMPORTANTE: A Receita Federal pode exigir captcha. Este script tenta o
    fluxo mais simples. Se falhar, usar o script Selenium como fallback.

    Args:
        cpf: CPF (somente digitos, 11 caracteres).
        dt_nascimento: Data de nascimento (dd/mm/aaaa).
    """
    print(f"[Receita PF] Iniciando para CPF: {cpf}")

    cpf_limpo = re.sub(r"\D", "", cpf)

    base_url = "https://solucoes.receita.fazenda.gov.br/Servicos/certidaointernet/PF"

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    try:
        # 1) GET pagina inicial
        print("[Receita PF] Obtendo pagina inicial...")
        r1 = session.get(f"{base_url}/Emitir", timeout=30, verify=True)
        r1.raise_for_status()
        print(f"[Receita PF] Pagina obtida (status {r1.status_code})")

        # Extrair __RequestVerificationToken
        token = None
        m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', r1.text)
        if m:
            token = m.group(1)
            print("[Receita PF] Token anti-forgery extraido.")

        # 2) POST para emitir
        print("[Receita PF] Tentando emitir certidao...")
        payload = {
            "NI": cpf_limpo,
            "DataNascimento": dt_nascimento,
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
        print(f"[Receita PF] Resposta recebida ({len(r2.content)} bytes, content-type: {r2.headers.get('Content-Type', 'N/A')})")

        content_type = r2.headers.get("Content-Type", "")

        if "application/pdf" in content_type:
            print("[Receita PF] Resposta eh PDF direto.")
            pdf_path = save_bytes_as_pdf(r2.content, "certidao_receita_pf.pdf")
        elif len(r2.text) > 500:
            if "captcha" in r2.text.lower() or "recaptcha" in r2.text.lower():
                return {
                    "status": "erro",
                    "link": None,
                    "mensagem": "Receita Federal exige captcha. Use o script Selenium como fallback.",
                }
            print("[Receita PF] Convertendo HTML para PDF...")
            pdf_path = html_to_pdf(r2.text, "certidao_receita_pf.pdf")
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
        print("[Receita PF] Fazendo upload do PDF...")
        link = upload_pdf(pdf_path)
        if not link:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Falha no upload do PDF.",
            }

        print(f"[Receita PF] Sucesso! Link: {link}")
        return {
            "status": "sucesso",
            "link": link,
            "mensagem": "Certidao Receita Federal PF emitida com sucesso.",
        }

    except requests.exceptions.RequestException as e:
        print(f"[Receita PF] Erro de rede: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro de rede: {e}",
        }
    except Exception as e:
        print(f"[Receita PF] Erro inesperado: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro inesperado: {e}",
        }


if __name__ == "__main__":
    import sys
    cpf = sys.argv[1] if len(sys.argv) > 1 else "00000000000"
    dt = sys.argv[2] if len(sys.argv) > 2 else "01/01/1990"
    result = emitir_certidao_receita_pf(cpf, dt)
    print(result)

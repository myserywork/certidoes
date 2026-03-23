"""
STJ - Certidao Pessoa Juridica (HTTP-only, sem browser)
Endpoint: https://processo.stj.jus.br/processo/certidao/
"""

import subprocess
import tempfile
import os
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def emitir_certidao_stj_pj(cnpj: str) -> dict:
    """Emite certidao negativa do STJ para pessoa juridica (CNPJ)."""
    print(f"[STJ PJ] Iniciando para CNPJ: {cnpj}")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    try:
        # 1) GET para obter cookies de sessao
        print("[STJ PJ] Obtendo sessao...")
        r1 = session.get(
            "https://processo.stj.jus.br/processo/certidao/emissao",
            timeout=30,
            verify=True,
        )
        r1.raise_for_status()
        print(f"[STJ PJ] Sessao obtida (status {r1.status_code})")

        # 2) POST para emitir certidao
        print("[STJ PJ] Emitindo certidao...")
        payload = {
            "acao": "pesquisarParte",
            "certidaoTipo": "pessoajuridicaconstanadaconsta",
            "parteCNPJ": cnpj,
            "certidaoProcessosEmTramite": "1",
            "certidaoEleitoralPublicaParteCPF": "",
        }
        r2 = session.post(
            "https://processo.stj.jus.br/processo/certidao/emitir",
            data=payload,
            timeout=60,
            verify=True,
        )
        r2.raise_for_status()
        print(f"[STJ PJ] Resposta recebida ({len(r2.text)} bytes)")

        if len(r2.text) < 200:
            return {
                "status": "erro",
                "link": None,
                "mensagem": f"Resposta muito curta ({len(r2.text)} bytes). Possivel bloqueio.",
            }

        # 3) HTML -> PDF
        print("[STJ PJ] Gerando PDF...")
        pdf_path = html_to_pdf(r2.text, "certidao_stj_pj.pdf")
        if not pdf_path:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Falha ao gerar PDF via Chrome headless.",
            }

        # 4) Upload
        print("[STJ PJ] Fazendo upload do PDF...")
        link = upload_pdf(pdf_path)
        if not link:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Falha no upload do PDF.",
            }

        print(f"[STJ PJ] Sucesso! Link: {link}")
        return {
            "status": "sucesso",
            "link": link,
            "mensagem": "Certidao STJ PJ emitida com sucesso.",
        }

    except requests.exceptions.RequestException as e:
        print(f"[STJ PJ] Erro de rede: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro de rede: {e}",
        }
    except Exception as e:
        print(f"[STJ PJ] Erro inesperado: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro inesperado: {e}",
        }


if __name__ == "__main__":
    import sys
    cnpj = sys.argv[1] if len(sys.argv) > 1 else "00000000000100"
    result = emitir_certidao_stj_pj(cnpj)
    print(result)

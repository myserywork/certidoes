"""
TJGO - Busca de Processos (HTTP-only, sem browser)
Endpoint: https://projudi.tjgo.jus.br/BuscaProcesso
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

def emitir_certidao_tjgo_processos(cpf_cnpj: str) -> dict:
    """Busca processos no TJGO por CPF/CNPJ.

    Args:
        cpf_cnpj: CPF ou CNPJ (somente digitos).
    """
    print(f"[TJGO Processos] Iniciando para CPF/CNPJ: {cpf_cnpj}")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://projudi.tjgo.jus.br/",
    })

    try:
        # POST para buscar processos (TipoArea=0 = todas as areas)
        print("[TJGO Processos] Buscando processos...")
        payload = {
            "CpfCnpjParte": cpf_cnpj,
            "NrProcesso": "",
            "NrPrecatorio": "",
            "NomeParte": "",
            "TipoArea": "0",
            "PaginaAtual": "1",
        }
        r = session.post(
            "https://projudi.tjgo.jus.br/BuscaProcesso",
            data=payload,
            timeout=60,
            verify=True,
        )
        r.raise_for_status()
        print(f"[TJGO Processos] Resposta recebida ({len(r.text)} bytes)")

        if len(r.text) < 200:
            return {
                "status": "erro",
                "link": None,
                "mensagem": f"Resposta muito curta ({len(r.text)} bytes). Possivel bloqueio.",
            }

        # HTML -> PDF
        print("[TJGO Processos] Gerando PDF...")
        pdf_path = html_to_pdf(r.text, "certidao_tjgo_processos.pdf")
        if not pdf_path:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Falha ao gerar PDF via Chrome headless.",
            }

        # Upload
        print("[TJGO Processos] Fazendo upload do PDF...")
        link = upload_pdf(pdf_path)
        if not link:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Falha no upload do PDF.",
            }

        print(f"[TJGO Processos] Sucesso! Link: {link}")
        return {
            "status": "sucesso",
            "link": link,
            "mensagem": "Busca de processos TJGO concluida com sucesso.",
        }

    except requests.exceptions.RequestException as e:
        print(f"[TJGO Processos] Erro de rede: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro de rede: {e}",
        }
    except Exception as e:
        print(f"[TJGO Processos] Erro inesperado: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro inesperado: {e}",
        }


if __name__ == "__main__":
    import sys
    cpf_cnpj = sys.argv[1] if len(sys.argv) > 1 else "00000000000"
    result = emitir_certidao_tjgo_processos(cpf_cnpj)
    print(result)

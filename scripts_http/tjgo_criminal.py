"""
TJGO - Certidao Criminal (HTTP-only, sem browser)
Endpoint: https://projudi.tjgo.jus.br/CertidaoNegativaPositivaPublica
Igual ao civil mas com TipoArea=2.
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

def emitir_certidao_tjgo_criminal(nome: str, cpf: str, nm_mae: str, dt_nascimento: str) -> dict:
    """Emite certidao criminal do TJGO via Projudi.

    Args:
        nome: Nome completo da pessoa.
        cpf: CPF (somente digitos).
        nm_mae: Nome da mae.
        dt_nascimento: Data de nascimento (dd/mm/aaaa).
    """
    print(f"[TJGO Criminal] Iniciando para CPF: {cpf}")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://projudi.tjgo.jus.br/",
    })

    try:
        # POST para emitir certidao criminal (TipoArea=2)
        print("[TJGO Criminal] Emitindo certidao...")
        payload = {
            "Nome": nome,
            "Cpf": cpf,
            "NomeMae": nm_mae,
            "DataNascimento": dt_nascimento,
            "TipoArea": "2",
            "PaginaAtual": "1",
            "InteressePessoal": "S",
        }
        r = session.post(
            "https://projudi.tjgo.jus.br/CertidaoNegativaPositivaPublica",
            data=payload,
            timeout=60,
            verify=True,
        )
        r.raise_for_status()
        print(f"[TJGO Criminal] Resposta recebida ({len(r.text)} bytes)")

        if len(r.text) < 200:
            return {
                "status": "erro",
                "link": None,
                "mensagem": f"Resposta muito curta ({len(r.text)} bytes). Possivel bloqueio.",
            }

        # HTML -> PDF
        print("[TJGO Criminal] Gerando PDF...")
        pdf_path = html_to_pdf(r.text, "certidao_tjgo_criminal.pdf")
        if not pdf_path:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Falha ao gerar PDF via Chrome headless.",
            }

        # Upload
        print("[TJGO Criminal] Fazendo upload do PDF...")
        link = upload_pdf(pdf_path)
        if not link:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Falha no upload do PDF.",
            }

        print(f"[TJGO Criminal] Sucesso! Link: {link}")
        return {
            "status": "sucesso",
            "link": link,
            "mensagem": "Certidao TJGO Criminal emitida com sucesso.",
        }

    except requests.exceptions.RequestException as e:
        print(f"[TJGO Criminal] Erro de rede: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro de rede: {e}",
        }
    except Exception as e:
        print(f"[TJGO Criminal] Erro inesperado: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro inesperado: {e}",
        }


if __name__ == "__main__":
    result = emitir_certidao_tjgo_criminal("TESTE DA SILVA", "00000000000", "MAE TESTE", "01/01/1990")
    print(result)

"""
STJ - Certidao Pessoa Fisica (HTTP-only, sem browser)
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
        chrome = "google-chrome"  # Linux

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

def emitir_certidao_stj(cpf: str) -> dict:
    """Emite certidao negativa do STJ para pessoa fisica (CPF)."""
    print(f"[STJ PF] Iniciando para CPF: {cpf}")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    try:
        # 1) GET para obter cookies de sessao
        print("[STJ PF] Obtendo sessao...")
        r1 = session.get(
            "https://processo.stj.jus.br/processo/certidao/emissao",
            timeout=30,
            verify=True,
        )
        r1.raise_for_status()
        print(f"[STJ PF] Sessao obtida (status {r1.status_code})")

        # 2) POST para emitir certidao
        print("[STJ PF] Emitindo certidao...")
        payload = {
            "acao": "pesquisarParte",
            "certidaoTipo": "pessoafisicaconstanadaconsta",
            "parteCPF": cpf,
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
        print(f"[STJ PF] Resposta recebida ({len(r2.text)} bytes)")

        # 3) Verificar se retornou conteudo valido
        if len(r2.text) < 200:
            return {
                "status": "erro",
                "link": None,
                "mensagem": f"Resposta muito curta ({len(r2.text)} bytes). Possivel bloqueio.",
            }

        # 4) HTML -> PDF
        print("[STJ PF] Gerando PDF...")
        pdf_path = html_to_pdf(r2.text, "certidao_stj_pf.pdf")
        if not pdf_path:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Falha ao gerar PDF via Chrome headless.",
            }

        # 5) Upload
        print("[STJ PF] Fazendo upload do PDF...")
        link = upload_pdf(pdf_path)
        if not link:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Falha no upload do PDF.",
            }

        print(f"[STJ PF] Sucesso! Link: {link}")
        return {
            "status": "sucesso",
            "link": link,
            "mensagem": "Certidao STJ PF emitida com sucesso.",
        }

    except requests.exceptions.RequestException as e:
        print(f"[STJ PF] Erro de rede: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro de rede: {e}",
        }
    except Exception as e:
        print(f"[STJ PF] Erro inesperado: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro inesperado: {e}",
        }


if __name__ == "__main__":
    import sys
    cpf = sys.argv[1] if len(sys.argv) > 1 else "00000000000"
    result = emitir_certidao_stj(cpf)
    print(result)

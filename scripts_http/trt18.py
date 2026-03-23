"""
TRT18 - Certidao Processual (HTTP-only, sem browser)
Endpoint: https://sistemas.trt18.jus.br/consultasPortal/pages/Processuais/Certidao.seam
JSF (Java Server Faces) - requer extração de javax.faces.ViewState.
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


def extract_view_state(html: str) -> str:
    """Extrai javax.faces.ViewState do HTML JSF."""
    # Tenta o padrao padrao do JSF
    m = re.search(
        r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"',
        html,
    )
    if m:
        return m.group(1)
    # Tenta com id
    m = re.search(
        r'id="javax\.faces\.ViewState"[^>]*value="([^"]+)"',
        html,
    )
    if m:
        return m.group(1)
    # Fallback: qualquer hidden com ViewState
    m = re.search(r'ViewState[^>]*value="([^"]+)"', html)
    if m:
        return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def emitir_certidao_trt18(cpf_cnpj: str) -> dict:
    """Emite certidao processual do TRT18 (18a Regiao - Goias).

    Args:
        cpf_cnpj: CPF ou CNPJ (somente digitos).
    """
    print(f"[TRT18] Iniciando para CPF/CNPJ: {cpf_cnpj}")

    base_url = "https://sistemas.trt18.jus.br/consultasPortal/pages/Processuais/Certidao.seam"

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    try:
        # 1) GET - obter pagina e extrair ViewState
        print("[TRT18] Obtendo pagina JSF...")
        r1 = session.get(base_url, timeout=30, verify=True)
        r1.raise_for_status()
        print(f"[TRT18] Pagina obtida (status {r1.status_code})")

        view_state = extract_view_state(r1.text)
        if not view_state:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Nao foi possivel extrair javax.faces.ViewState da pagina JSF.",
            }
        print(f"[TRT18] ViewState extraido ({len(view_state)} chars)")

        # Detectar se eh CPF (11 dig) ou CNPJ (14 dig)
        doc_limpo = re.sub(r"\D", "", cpf_cnpj)
        is_cpf = len(doc_limpo) <= 11

        # 2) POST - submeter formulario JSF
        # Os nomes dos campos JSF variam; estes sao os mais comuns para TRT18.
        # Se o formulario usar nomes diferentes, ajustar aqui.
        print("[TRT18] Submetendo formulario...")
        payload = {
            "javax.faces.ViewState": view_state,
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": "formCertidao:btnEmitir",
            "javax.faces.partial.execute": "@all",
            "javax.faces.partial.render": "@all",
            "formCertidao": "formCertidao",
            "formCertidao:tipoPessoa": "CPF" if is_cpf else "CNPJ",
            "formCertidao:cpfCnpj": doc_limpo,
            "formCertidao:btnEmitir": "formCertidao:btnEmitir",
        }

        r2 = session.post(
            base_url,
            data=payload,
            timeout=60,
            verify=True,
            headers={
                "Faces-Request": "partial/ajax",
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": base_url,
            },
        )
        r2.raise_for_status()
        print(f"[TRT18] Resposta recebida ({len(r2.text)} bytes)")

        # JSF pode retornar redirect ou conteudo parcial.
        # Tentar pegar a pagina completa de resultado.
        # Se a resposta contem um redirect, seguir.
        if "redirect" in r2.text.lower() or len(r2.text) < 500:
            # Tentar GET na mesma URL para obter o resultado renderizado
            print("[TRT18] Buscando resultado renderizado...")
            r3 = session.get(base_url, timeout=30, verify=True)
            r3.raise_for_status()
            html_result = r3.text
        else:
            html_result = r2.text

        if len(html_result) < 200:
            return {
                "status": "erro",
                "link": None,
                "mensagem": f"Resposta muito curta ({len(html_result)} bytes).",
            }

        # HTML -> PDF
        print("[TRT18] Gerando PDF...")
        pdf_path = html_to_pdf(html_result, "certidao_trt18.pdf")
        if not pdf_path:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Falha ao gerar PDF via Chrome headless.",
            }

        # Upload
        print("[TRT18] Fazendo upload do PDF...")
        link = upload_pdf(pdf_path)
        if not link:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Falha no upload do PDF.",
            }

        print(f"[TRT18] Sucesso! Link: {link}")
        return {
            "status": "sucesso",
            "link": link,
            "mensagem": "Certidao TRT18 emitida com sucesso.",
        }

    except requests.exceptions.RequestException as e:
        print(f"[TRT18] Erro de rede: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro de rede: {e}",
        }
    except Exception as e:
        print(f"[TRT18] Erro inesperado: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro inesperado: {e}",
        }


if __name__ == "__main__":
    import sys
    cpf_cnpj = sys.argv[1] if len(sys.argv) > 1 else "00000000000"
    result = emitir_certidao_trt18(cpf_cnpj)
    print(result)

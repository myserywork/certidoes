"""
TRF1 - Certidao (HTTP-only, sem browser)

NOTA: O TRF1 usa um app Angular em
https://sistemas.trf1.jus.br/certidao/#/solicitacao
que faz chamadas a APIs REST internas. Os endpoints abaixo sao best-guess
baseados em padroes comuns de Angular apps de tribunais e podem precisar de
ajuste apos inspecao via DevTools do browser.

Endpoints provaveis:
- GET  /certidao/api/tipo-certidao → lista tipos disponiveis
- POST /certidao/api/certidao/solicitar → solicita a certidao
- GET  /certidao/api/certidao/{id}/pdf → baixa o PDF

Alternativa (mais comum em TRFs):
- POST /certidao/api/emitir com JSON body
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

def emitir_certidao_trf1(tipo: str, doc_tipo: str, documento: str) -> dict:
    """Emite certidao do TRF1 (1a Regiao).

    IMPORTANTE: Os endpoints da API do TRF1 precisam ser verificados via
    DevTools. Este script tenta multiplas abordagens conhecidas.

    Args:
        tipo: Tipo de certidao (ex: "criminal", "civel", "eleitoral").
        doc_tipo: Tipo de documento ("cpf" ou "cnpj").
        documento: Numero do documento (somente digitos).
    """
    print(f"[TRF1] Iniciando para {doc_tipo.upper()}: {documento}, tipo: {tipo}")

    doc_limpo = re.sub(r"\D", "", documento)
    base_api = "https://sistemas.trf1.jus.br/certidao"

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": f"{base_api}/",
        "Origin": "https://sistemas.trf1.jus.br",
    })

    try:
        # 1) GET pagina Angular para obter cookies/XSRF token
        print("[TRF1] Obtendo pagina Angular...")
        r1 = session.get(f"{base_api}/", timeout=30, verify=True)
        # Nao precisa dar raise_for_status pois Angular apps retornam o index.html

        # Verificar se tem XSRF token nos cookies
        xsrf = session.cookies.get("XSRF-TOKEN") or session.cookies.get("_csrf")
        if xsrf:
            session.headers["X-XSRF-TOKEN"] = xsrf
            print(f"[TRF1] XSRF token encontrado.")

        # 2) Mapear tipo de certidao para o codigo esperado pela API
        tipo_map = {
            "criminal": "CRIMINAL",
            "civel": "CIVEL",
            "eleitoral": "ELEITORAL",
            "distribuicao": "DISTRIBUICAO",
        }
        tipo_api = tipo_map.get(tipo.lower(), tipo.upper())

        # 3) Tentar POST na API REST
        # Abordagem 1: JSON body (padrao Angular)
        print("[TRF1] Tentando emitir via API REST (JSON)...")
        json_payload = {
            "tipoCertidao": tipo_api,
            "tipoDocumento": doc_tipo.upper(),
            "documento": doc_limpo,
        }

        # Tentar varios endpoints possiveis
        endpoints = [
            f"{base_api}/api/certidao/solicitar",
            f"{base_api}/api/emitir",
            f"{base_api}/api/certidao/emitir",
            f"{base_api}/api/certidoes/solicitar",
        ]

        r2 = None
        for endpoint in endpoints:
            try:
                print(f"[TRF1] Tentando: {endpoint}")
                r2 = session.post(
                    endpoint,
                    json=json_payload,
                    timeout=60,
                    verify=True,
                )
                if r2.status_code < 500:
                    print(f"[TRF1] Endpoint respondeu com status {r2.status_code}")
                    break
            except requests.exceptions.RequestException:
                continue

        if r2 is None or r2.status_code >= 500:
            # Fallback: tentar form-data no endpoint principal
            print("[TRF1] APIs REST falharam. Tentando form-data...")
            r2 = session.post(
                f"{base_api}/",
                data={
                    "tipoCertidao": tipo_api,
                    "tipoDocumento": doc_tipo.upper(),
                    "documento": doc_limpo,
                },
                timeout=60,
                verify=True,
            )

        if r2 is None:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Nenhum endpoint da API do TRF1 respondeu.",
            }

        print(f"[TRF1] Resposta final: status={r2.status_code}, tamanho={len(r2.content)} bytes")

        content_type = r2.headers.get("Content-Type", "")

        # Processar resposta
        if "application/pdf" in content_type:
            print("[TRF1] Resposta eh PDF direto.")
            pdf_path = save_bytes_as_pdf(r2.content, "certidao_trf1.pdf")
        elif "application/json" in content_type:
            # API retornou JSON - pode conter URL do PDF ou mensagem de erro
            try:
                data = r2.json()
                print(f"[TRF1] JSON recebido: {list(data.keys()) if isinstance(data, dict) else 'array'}")

                # Tentar extrair URL do PDF do JSON
                pdf_url = None
                if isinstance(data, dict):
                    pdf_url = (data.get("urlPdf") or data.get("url") or
                               data.get("linkPdf") or data.get("link"))
                    if data.get("erro") or data.get("mensagem"):
                        msg = data.get("erro") or data.get("mensagem", "Erro desconhecido")
                        return {
                            "status": "erro",
                            "link": None,
                            "mensagem": f"API retornou: {msg}",
                        }

                if pdf_url:
                    print(f"[TRF1] Baixando PDF de: {pdf_url}")
                    r3 = session.get(pdf_url, timeout=30, verify=True)
                    r3.raise_for_status()
                    pdf_path = save_bytes_as_pdf(r3.content, "certidao_trf1.pdf")
                else:
                    # Converter JSON para HTML legivel e gerar PDF
                    import json
                    html = f"<html><body><pre>{json.dumps(data, indent=2, ensure_ascii=False)}</pre></body></html>"
                    pdf_path = html_to_pdf(html, "certidao_trf1.pdf")
            except ValueError:
                pdf_path = html_to_pdf(r2.text, "certidao_trf1.pdf")
        elif len(r2.text) > 500:
            print("[TRF1] Convertendo HTML para PDF...")
            pdf_path = html_to_pdf(r2.text, "certidao_trf1.pdf")
        else:
            return {
                "status": "erro",
                "link": None,
                "mensagem": f"Resposta inesperada (status={r2.status_code}, {len(r2.content)} bytes). "
                            "Endpoints da API podem estar incorretos - verificar via DevTools.",
            }

        if not pdf_path:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Falha ao gerar/salvar PDF.",
            }

        # Upload
        print("[TRF1] Fazendo upload do PDF...")
        link = upload_pdf(pdf_path)
        if not link:
            return {
                "status": "erro",
                "link": None,
                "mensagem": "Falha no upload do PDF.",
            }

        print(f"[TRF1] Sucesso! Link: {link}")
        return {
            "status": "sucesso",
            "link": link,
            "mensagem": "Certidao TRF1 emitida com sucesso.",
        }

    except requests.exceptions.RequestException as e:
        print(f"[TRF1] Erro de rede: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro de rede: {e}",
        }
    except Exception as e:
        print(f"[TRF1] Erro inesperado: {e}")
        return {
            "status": "falha",
            "link": None,
            "mensagem": f"Erro inesperado: {e}",
        }


if __name__ == "__main__":
    import sys
    tipo = sys.argv[1] if len(sys.argv) > 1 else "criminal"
    doc_tipo = sys.argv[2] if len(sys.argv) > 2 else "cpf"
    documento = sys.argv[3] if len(sys.argv) > 3 else "00000000000"
    result = emitir_certidao_trf1(tipo, doc_tipo, documento)
    print(result)

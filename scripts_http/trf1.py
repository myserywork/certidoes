"""TRF1 - Certidao 1a Regiao (HTTP-only, sem browser)"""
import re
import json
import tempfile
import os
import requests
from scripts_http._shared import clean_certidao_html, html_to_pdf, upload_pdf

TITULO = "Certidao TRF1"
ORGAO = "TRF 1a Regiao"

def emitir_certidao_trf1(tipo: str, doc_tipo: str, documento: str) -> dict:
    print(f"[TRF1] Iniciando para {doc_tipo.upper()}: {documento}, tipo: {tipo}")
    doc_limpo = re.sub(r"\D", "", documento)
    base_api = "https://sistemas.trf1.jus.br/certidao"
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{base_api}/",
        "Origin": "https://sistemas.trf1.jus.br",
    })
    try:
        print("[TRF1] Obtendo pagina Angular...")
        r1 = session.get(f"{base_api}/", timeout=30)
        xsrf = session.cookies.get("XSRF-TOKEN") or session.cookies.get("_csrf")
        if xsrf:
            session.headers["X-XSRF-TOKEN"] = xsrf

        tipo_map = {"criminal": "CRIMINAL", "civel": "CIVEL", "eleitoral": "ELEITORAL", "distribuicao": "DISTRIBUICAO"}
        tipo_api = tipo_map.get(tipo.lower(), tipo.upper())

        json_payload = {"tipoCertidao": tipo_api, "tipoDocumento": doc_tipo.upper(), "documento": doc_limpo}
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
                r2 = session.post(endpoint, json=json_payload, timeout=60)
                if r2.status_code < 500:
                    break
            except requests.exceptions.RequestException:
                continue

        if r2 is None or r2.status_code >= 500:
            print("[TRF1] APIs REST falharam. Tentando form-data...")
            r2 = session.post(f"{base_api}/",
                data={"tipoCertidao": tipo_api, "tipoDocumento": doc_tipo.upper(), "documento": doc_limpo},
                timeout=60)

        if r2 is None:
            return {"status": "erro", "link": None, "mensagem": "Nenhum endpoint da API do TRF1 respondeu."}

        print(f"[TRF1] Resposta (status={r2.status_code}, {len(r2.content)} bytes)")
        content_type = r2.headers.get("Content-Type", "")
        pdf_path = None

        if "application/pdf" in content_type:
            tmpdir = tempfile.mkdtemp()
            pdf_path = os.path.join(tmpdir, "certidao_trf1.pdf")
            with open(pdf_path, "wb") as f:
                f.write(r2.content)
            if os.path.getsize(pdf_path) <= 100:
                pdf_path = None
        elif "application/json" in content_type:
            try:
                data = r2.json()
                if isinstance(data, dict):
                    if data.get("erro") or data.get("mensagem"):
                        msg = data.get("erro") or data.get("mensagem", "Erro desconhecido")
                        return {"status": "erro", "link": None, "mensagem": f"API retornou: {msg}"}
                    pdf_url = data.get("urlPdf") or data.get("url") or data.get("linkPdf") or data.get("link")
                    if pdf_url:
                        r3 = session.get(pdf_url, timeout=30)
                        r3.raise_for_status()
                        tmpdir = tempfile.mkdtemp()
                        pdf_path = os.path.join(tmpdir, "certidao_trf1.pdf")
                        with open(pdf_path, "wb") as f:
                            f.write(r3.content)
                    else:
                        html = f"<html><body><pre>{json.dumps(data, indent=2, ensure_ascii=False)}</pre></body></html>"
                        cleaned = clean_certidao_html(html, TITULO, ORGAO)
                        pdf_path = html_to_pdf(cleaned, "certidao_trf1.pdf")
            except ValueError:
                cleaned = clean_certidao_html(r2.text, TITULO, ORGAO)
                pdf_path = html_to_pdf(cleaned, "certidao_trf1.pdf")
        elif len(r2.text) > 500:
            cleaned = clean_certidao_html(r2.text, TITULO, ORGAO)
            pdf_path = html_to_pdf(cleaned, "certidao_trf1.pdf")
        else:
            return {"status": "erro", "link": None, "mensagem": "Resposta inesperada. Endpoints da API podem estar incorretos."}

        if not pdf_path:
            return {"status": "erro", "link": None, "mensagem": "Falha ao gerar PDF"}

        link = upload_pdf(pdf_path)
        if not link:
            return {"status": "erro", "link": None, "mensagem": "Falha no upload"}

        print(f"[TRF1] Sucesso! Link: {link}")
        return {"status": "sucesso", "link": link, "mensagem": "Certidao TRF1 emitida com sucesso."}
    except Exception as e:
        return {"status": "erro", "link": None, "mensagem": f"Erro: {str(e)[:200]}"}

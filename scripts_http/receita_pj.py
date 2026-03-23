"""Receita Federal - Certidao Pessoa Juridica (HTTP-only, sem browser)"""
import re
import tempfile
import os
import requests
from scripts_http._shared import clean_certidao_html, html_to_pdf, upload_pdf

TITULO = "Certidao Receita Federal PJ"
ORGAO = "Receita Federal do Brasil"

def emitir_certidao_receita_pj(cnpj: str) -> dict:
    print(f"[Receita PJ] Iniciando para CNPJ: {cnpj}")
    cnpj_limpo = re.sub(r"\D", "", cnpj)
    base_url = "https://solucoes.receita.fazenda.gov.br/Servicos/certidaointernet/PJ"
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    try:
        print("[Receita PJ] Obtendo pagina inicial...")
        r1 = session.get(f"{base_url}/Emitir", timeout=30)
        r1.raise_for_status()

        token = None
        m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', r1.text)
        if m:
            token = m.group(1)

        print("[Receita PJ] Emitindo certidao...")
        payload = {"NI": cnpj_limpo}
        if token:
            payload["__RequestVerificationToken"] = token

        r = session.post(f"{base_url}/Emitir", data=payload, timeout=60,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": f"{base_url}/Emitir", "Origin": "https://solucoes.receita.fazenda.gov.br"})
        r.raise_for_status()
        print(f"[Receita PJ] Resposta ({len(r.content)} bytes)")

        content_type = r.headers.get("Content-Type", "")

        if "application/pdf" in content_type:
            tmpdir = tempfile.mkdtemp()
            pdf_path = os.path.join(tmpdir, "certidao_receita_pj.pdf")
            with open(pdf_path, "wb") as f:
                f.write(r.content)
            if os.path.getsize(pdf_path) <= 100:
                pdf_path = None
        elif len(r.text) > 500:
            if "captcha" in r.text.lower() or "recaptcha" in r.text.lower():
                return {"status": "erro", "link": None, "mensagem": "Receita Federal exige captcha. Use o script Selenium como fallback."}
            cleaned = clean_certidao_html(r.text, TITULO, ORGAO)
            pdf_path = html_to_pdf(cleaned, "certidao_receita_pj.pdf")
        else:
            return {"status": "erro", "link": None, "mensagem": "Resposta inesperada. Possivel bloqueio ou captcha."}

        if not pdf_path:
            return {"status": "erro", "link": None, "mensagem": "Falha ao gerar PDF"}

        link = upload_pdf(pdf_path)
        if not link:
            return {"status": "erro", "link": None, "mensagem": "Falha no upload"}

        print(f"[Receita PJ] Sucesso! Link: {link}")
        return {"status": "sucesso", "link": link, "mensagem": "Certidao Receita Federal PJ emitida com sucesso."}
    except Exception as e:
        return {"status": "erro", "link": None, "mensagem": f"Erro: {str(e)[:200]}"}

"""Receita Federal - Certidao Pessoa Fisica (HTTP-only, sem browser)"""
import re
import tempfile
import os
import requests
from scripts_http._shared import clean_certidao_html, html_to_pdf, upload_pdf

TITULO = "Certidao Receita Federal PF"
ORGAO = "Receita Federal do Brasil"

def emitir_certidao_receita_pf(cpf: str, dt_nascimento: str) -> dict:
    print(f"[Receita PF] Iniciando para CPF: {cpf}")
    cpf_limpo = re.sub(r"\D", "", cpf)
    base_url = "https://solucoes.receita.fazenda.gov.br/Servicos/certidaointernet/PF"
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    try:
        print("[Receita PF] Obtendo pagina inicial...")
        r1 = session.get(f"{base_url}/Emitir", timeout=30)
        r1.raise_for_status()

        token = None
        m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', r1.text)
        if m:
            token = m.group(1)

        print("[Receita PF] Emitindo certidao...")
        payload = {"NI": cpf_limpo, "DataNascimento": dt_nascimento}
        if token:
            payload["__RequestVerificationToken"] = token

        r = session.post(f"{base_url}/Emitir", data=payload, timeout=60,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": f"{base_url}/Emitir", "Origin": "https://solucoes.receita.fazenda.gov.br"})
        r.raise_for_status()
        print(f"[Receita PF] Resposta ({len(r.content)} bytes)")

        content_type = r.headers.get("Content-Type", "")

        if "application/pdf" in content_type:
            tmpdir = tempfile.mkdtemp()
            pdf_path = os.path.join(tmpdir, "certidao_receita_pf.pdf")
            with open(pdf_path, "wb") as f:
                f.write(r.content)
            if os.path.getsize(pdf_path) <= 100:
                pdf_path = None
        elif len(r.text) > 500:
            if "captcha" in r.text.lower() or "recaptcha" in r.text.lower():
                return {"status": "erro", "link": None, "mensagem": "Receita Federal exige captcha. Use o script Selenium como fallback."}
            cleaned = clean_certidao_html(r.text, TITULO, ORGAO)
            pdf_path = html_to_pdf(cleaned, "certidao_receita_pf.pdf")
        else:
            return {"status": "erro", "link": None, "mensagem": "Resposta inesperada. Possivel bloqueio ou captcha."}

        if not pdf_path:
            return {"status": "erro", "link": None, "mensagem": "Falha ao gerar PDF"}

        link = upload_pdf(pdf_path)
        if not link:
            return {"status": "erro", "link": None, "mensagem": "Falha no upload"}

        print(f"[Receita PF] Sucesso! Link: {link}")
        return {"status": "sucesso", "link": link, "mensagem": "Certidao Receita Federal PF emitida com sucesso."}
    except Exception as e:
        return {"status": "erro", "link": None, "mensagem": f"Erro: {str(e)[:200]}"}

"""TRT18 - Certidao Processual Goias (HTTP-only, sem browser)"""
import re
import requests
from scripts_http._shared import clean_certidao_html, html_to_pdf, upload_pdf

TITULO = "Certidao TRT18"
ORGAO = "TRT 18a Regiao - Goias"

def emitir_certidao_trt18(cpf_cnpj: str) -> dict:
    print(f"[TRT18] Iniciando para CPF/CNPJ: {cpf_cnpj}")
    base_url = "https://sistemas.trt18.jus.br/consultasPortal/pages/Processuais/Certidao.seam"
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    try:
        print("[TRT18] Obtendo pagina JSF...")
        r1 = session.get(base_url, timeout=30)
        r1.raise_for_status()

        view_state = None
        for pattern in [
            r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"',
            r'id="javax\.faces\.ViewState"[^>]*value="([^"]+)"',
            r'ViewState[^>]*value="([^"]+)"',
        ]:
            m = re.search(pattern, r1.text)
            if m:
                view_state = m.group(1)
                break
        if not view_state:
            return {"status": "erro", "link": None, "mensagem": "Nao foi possivel extrair ViewState da pagina JSF."}

        doc_limpo = re.sub(r"\D", "", cpf_cnpj)
        is_cpf = len(doc_limpo) <= 11

        print("[TRT18] Submetendo formulario...")
        r2 = session.post(base_url,
            data={
                "javax.faces.ViewState": view_state,
                "javax.faces.partial.ajax": "true",
                "javax.faces.source": "formCertidao:btnEmitir",
                "javax.faces.partial.execute": "@all",
                "javax.faces.partial.render": "@all",
                "formCertidao": "formCertidao",
                "formCertidao:tipoPessoa": "CPF" if is_cpf else "CNPJ",
                "formCertidao:cpfCnpj": doc_limpo,
                "formCertidao:btnEmitir": "formCertidao:btnEmitir",
            },
            headers={
                "Faces-Request": "partial/ajax",
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": base_url,
            },
            timeout=60)
        r2.raise_for_status()

        if "redirect" in r2.text.lower() or len(r2.text) < 500:
            r3 = session.get(base_url, timeout=30)
            r3.raise_for_status()
            html_result = r3.text
        else:
            html_result = r2.text

        print(f"[TRT18] Resposta ({len(html_result)} bytes)")
        if len(html_result) < 200:
            return {"status": "erro", "link": None, "mensagem": "Resposta muito curta"}

        cleaned = clean_certidao_html(html_result, TITULO, ORGAO)
        pdf_path = html_to_pdf(cleaned, "certidao_trt18.pdf")
        if not pdf_path:
            return {"status": "erro", "link": None, "mensagem": "Falha ao gerar PDF"}

        link = upload_pdf(pdf_path)
        if not link:
            return {"status": "erro", "link": None, "mensagem": "Falha no upload"}

        print(f"[TRT18] Sucesso! Link: {link}")
        return {"status": "sucesso", "link": link, "mensagem": "Certidao TRT18 emitida com sucesso."}
    except Exception as e:
        return {"status": "erro", "link": None, "mensagem": f"Erro: {str(e)[:200]}"}

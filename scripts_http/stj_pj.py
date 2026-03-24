"""STJ - Certidao Pessoa Juridica (HTTP-only, retorna PDF real)"""
import os
import tempfile
import requests
from scripts_http._shared import clean_certidao_html, html_to_pdf, upload_pdf

def emitir_certidao_stj_pj(cnpj: str) -> dict:
    print(f"[STJ PJ] Iniciando para CNPJ: {cnpj}")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    try:
        session.get("https://processo.stj.jus.br/processo/certidao/emissao", timeout=15)

        # Step 1: pesquisar
        session.post("https://processo.stj.jus.br/processo/certidao/emitir",
            data={"acao": "pesquisarParte", "certidaoTipo": "pessoajuridicaconstanadaconsta",
                  "parteCNPJ": cnpj, "certidaoProcessosEmTramite": "1"},
            timeout=15)

        # Step 2: emitir (com sessao da pesquisa)
        print("[STJ PJ] Emitindo certidao...")
        r = session.post("https://processo.stj.jus.br/processo/certidao/emitir",
            data={"acao": "emitir", "certidaoTipo": "pessoajuridicaconstanadaconsta",
                  "parteCNPJ": cnpj, "certidaoProcessosEmTramite": "1"},
            timeout=30)

        is_pdf = r.content[:5] == b'%PDF-'
        print(f"[STJ PJ] Response: {r.status_code} | PDF={is_pdf} | {len(r.content)} bytes")

        if is_pdf and len(r.content) > 500:
            tmpdir = tempfile.mkdtemp()
            pdf_path = os.path.join(tmpdir, f"certidao_stj_pj_{cnpj}.pdf")
            with open(pdf_path, "wb") as f:
                f.write(r.content)
            link = upload_pdf(pdf_path)
            return {"status": "sucesso", "link": link, "tipo_certidao": "stj_pj", "mensagem": "Certidao STJ PJ emitida"}

        # Se nao retornou PDF, pode ser nada consta (gerar PDF do HTML)
        import re
        if "nada consta" in r.text.lower():
            cleaned = clean_certidao_html(r.text, "Certidao STJ PJ - Nada Consta", "Superior Tribunal de Justica")
            pdf_path = html_to_pdf(cleaned, f"certidao_stj_pj_{cnpj}.pdf")
            if pdf_path:
                link = upload_pdf(pdf_path)
                return {"status": "sucesso", "link": link, "tipo_certidao": "nada_consta", "mensagem": "STJ PJ: Nada consta"}
            return {"status": "sucesso", "link": None, "tipo_certidao": "nada_consta", "mensagem": "STJ PJ: Nada consta"}

        return {"status": "falha", "mensagem": "STJ nao retornou certidao"}
    except Exception as e:
        return {"status": "erro", "mensagem": f"Erro: {str(e)[:200]}"}

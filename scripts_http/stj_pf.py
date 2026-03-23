"""STJ - Certidao Pessoa Fisica (HTTP-only, sem browser)"""
import requests
from scripts_http._shared import clean_certidao_html, html_to_pdf, upload_pdf

TITULO = "Certidao STJ PF"
ORGAO = "Superior Tribunal de Justica"

def emitir_certidao_stj(cpf: str) -> dict:
    print(f"[STJ PF] Iniciando para CPF: {cpf}")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    try:
        print("[STJ PF] Obtendo sessao...")
        r1 = session.get("https://processo.stj.jus.br/processo/certidao/emissao", timeout=30)
        r1.raise_for_status()

        print("[STJ PF] Emitindo certidao...")
        r = session.post("https://processo.stj.jus.br/processo/certidao/emitir",
            data={"acao": "pesquisarParte", "certidaoTipo": "pessoafisicaconstanadaconsta", "parteCPF": cpf, "certidaoProcessosEmTramite": "1"},
            timeout=60)
        r.raise_for_status()
        print(f"[STJ PF] Resposta ({len(r.text)} bytes)")
        if len(r.text) < 200:
            return {"status": "erro", "link": None, "mensagem": "Resposta muito curta"}

        cleaned = clean_certidao_html(r.text, TITULO, ORGAO)
        pdf_path = html_to_pdf(cleaned, "certidao_stj_pf.pdf")
        if not pdf_path:
            return {"status": "erro", "link": None, "mensagem": "Falha ao gerar PDF"}

        link = upload_pdf(pdf_path)
        if not link:
            return {"status": "erro", "link": None, "mensagem": "Falha no upload"}

        print(f"[STJ PF] Sucesso! Link: {link}")
        return {"status": "sucesso", "link": link, "mensagem": "Certidao STJ PF emitida com sucesso."}
    except Exception as e:
        return {"status": "erro", "link": None, "mensagem": f"Erro: {str(e)[:200]}"}

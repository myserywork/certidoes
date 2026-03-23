"""TJGO - Certidao Civil (HTTP-only, sem browser)"""
import requests
from scripts_http._shared import clean_certidao_html, html_to_pdf, upload_pdf

TITULO = "Certidao Civel TJGO"
ORGAO = "TJGO - Civel 1o Grau"

def emitir_certidao_tjgo_civil(nome: str, cpf: str, nm_mae: str, dt_nascimento: str) -> dict:
    print(f"[TJGO Civil] Iniciando para CPF: {cpf}")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://projudi.tjgo.jus.br/",
    })
    try:
        print("[TJGO Civil] Emitindo certidao...")
        r = session.post("https://projudi.tjgo.jus.br/CertidaoNegativaPositivaPublica",
            data={"Nome": nome, "Cpf": cpf, "NomeMae": nm_mae, "DataNascimento": dt_nascimento, "TipoArea": "1", "PaginaAtual": "1", "InteressePessoal": "S"},
            timeout=60)
        r.raise_for_status()
        print(f"[TJGO Civil] Resposta ({len(r.text)} bytes)")
        if len(r.text) < 200:
            return {"status": "erro", "link": None, "mensagem": "Resposta muito curta"}

        cleaned = clean_certidao_html(r.text, TITULO, ORGAO)
        pdf_path = html_to_pdf(cleaned, "certidao_tjgo_civil.pdf")
        if not pdf_path:
            return {"status": "erro", "link": None, "mensagem": "Falha ao gerar PDF"}

        link = upload_pdf(pdf_path)
        if not link:
            return {"status": "erro", "link": None, "mensagem": "Falha no upload"}

        print(f"[TJGO Civil] Sucesso! Link: {link}")
        return {"status": "sucesso", "link": link, "mensagem": "Certidao TJGO Civil emitida com sucesso."}
    except Exception as e:
        return {"status": "erro", "link": None, "mensagem": f"Erro: {str(e)[:200]}"}

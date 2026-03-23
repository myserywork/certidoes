"""TJGO - Busca de Processos (HTTP-only, sem browser)"""
import requests
from scripts_http._shared import clean_certidao_html, html_to_pdf, upload_pdf

TITULO = "Consulta Processos TJGO"
ORGAO = "TJGO - Busca de Processos"

def emitir_certidao_tjgo_processos(cpf_cnpj: str) -> dict:
    print(f"[TJGO Processos] Iniciando para CPF/CNPJ: {cpf_cnpj}")
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://projudi.tjgo.jus.br/",
    })
    try:
        print("[TJGO Processos] Buscando processos...")
        r = session.post("https://projudi.tjgo.jus.br/BuscaProcesso",
            data={"CpfCnpjParte": cpf_cnpj, "NrProcesso": "", "NrPrecatorio": "", "NomeParte": "", "TipoArea": "0", "PaginaAtual": "1"},
            timeout=60)
        r.raise_for_status()
        print(f"[TJGO Processos] Resposta ({len(r.text)} bytes)")
        if len(r.text) < 200:
            return {"status": "erro", "link": None, "mensagem": "Resposta muito curta"}

        cleaned = clean_certidao_html(r.text, TITULO, ORGAO)
        pdf_path = html_to_pdf(cleaned, "certidao_tjgo_processos.pdf")
        if not pdf_path:
            return {"status": "erro", "link": None, "mensagem": "Falha ao gerar PDF"}

        link = upload_pdf(pdf_path)
        if not link:
            return {"status": "erro", "link": None, "mensagem": "Falha no upload"}

        print(f"[TJGO Processos] Sucesso! Link: {link}")
        return {"status": "sucesso", "link": link, "mensagem": "Busca de processos TJGO concluida com sucesso."}
    except Exception as e:
        return {"status": "erro", "link": None, "mensagem": f"Erro: {str(e)[:200]}"}

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
        "Referer": "https://projudi.tjgo.jus.br/CertidaoNegativaPositivaPublica?PaginaAtual=1&TipoArea=1",
    })
    try:
        # GET pagina para pegar cookies/sessao
        session.get("https://projudi.tjgo.jus.br/CertidaoNegativaPositivaPublica?PaginaAtual=1&TipoArea=1&InteressePessoal=", timeout=15)

        # POST com botao "Gerar Certidão"
        print("[TJGO Civil] Emitindo certidao...")
        r = session.post("https://projudi.tjgo.jus.br/CertidaoNegativaPositivaPublica",
            data={
                "Nome": nome, "Cpf": cpf, "NomeMae": nm_mae, "DataNascimento": dt_nascimento,
                "TipoArea": "1", "PaginaAtual": "1", "InteressePessoal": "S",
                "Territorio": "", "Finalidade": "",
                "btnGerarCertidao": "Gerar Certidão",
            }, timeout=60)
        r.raise_for_status()
        print(f"[TJGO Civil] Resposta ({len(r.text)} bytes)")

        # Verificar se retornou resultado ou formulario
        has_result = "CERTID" in r.text.upper() and ("DISTRIBUI" in r.text.upper() or "CERTIFICO" in r.text.upper() or "NADA CONSTA" in r.text.upper())

        if len(r.text) < 200:
            return {"status": "erro", "link": None, "mensagem": "Resposta muito curta"}

        if not has_result:
            print("[TJGO Civil] Sem resultado na resposta (formulario retornado)")
            return {"status": "falha", "link": None, "mensagem": "TJGO nao retornou certidao"}

        cleaned = clean_certidao_html(r.text, TITULO, ORGAO)
        pdf_path = html_to_pdf(cleaned, "certidao_tjgo_civil.pdf")
        if not pdf_path:
            return {"status": "erro", "link": None, "mensagem": "Falha ao gerar PDF"}

        link = upload_pdf(pdf_path)
        print(f"[TJGO Civil] Sucesso! Link: {link}")
        return {"status": "sucesso", "link": link, "tipo_certidao": "nada_consta" if "NADA CONSTA" in r.text.upper() else "positiva", "mensagem": "Certidao TJGO Civil emitida"}
    except Exception as e:
        return {"status": "erro", "link": None, "mensagem": f"Erro: {str(e)[:200]}"}

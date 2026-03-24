"""STJ - Certidao Pessoa Fisica (HTTP-only, retorna PDF real)"""
import os
import tempfile
import requests
from scripts_http._shared import upload_pdf

def emitir_certidao_stj(cpf: str) -> dict:
    print(f"[STJ PF] Iniciando para CPF: {cpf}")
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    try:
        # 1. GET sessao
        session.get("https://processo.stj.jus.br/processo/certidao/emissao", timeout=15)

        # 2. POST com acao=emitir retorna PDF direto
        print("[STJ PF] Emitindo certidao...")
        r = session.post("https://processo.stj.jus.br/processo/certidao/emitir",
            data={"acao": "emitir", "certidaoTipo": "pessoafisicaconstanadaconsta",
                  "parteCPF": cpf, "certidaoProcessosEmTramite": "1"},
            timeout=30)

        ct = r.headers.get("content-type", "")
        is_pdf = r.content[:5] == b'%PDF-'
        print(f"[STJ PF] Response: {r.status_code} | {ct[:30]} | PDF={is_pdf} | {len(r.content)} bytes")

        if is_pdf and len(r.content) > 500:
            # Salvar PDF
            tmpdir = tempfile.mkdtemp()
            pdf_path = os.path.join(tmpdir, f"certidao_stj_pf_{cpf}.pdf")
            with open(pdf_path, "wb") as f:
                f.write(r.content)
            link = upload_pdf(pdf_path)
            print(f"[STJ PF] Sucesso! PDF real {len(r.content)} bytes")
            return {"status": "sucesso", "link": link, "tipo_certidao": "stj_pf", "mensagem": "Certidao STJ PF emitida"}

        # Nao retornou PDF - verificar erro
        if "nenhum processo" in r.text.lower() or "nada consta" in r.text.lower():
            return {"status": "sucesso", "link": None, "tipo_certidao": "nada_consta", "mensagem": "STJ: Nada consta"}

        return {"status": "falha", "mensagem": f"STJ nao retornou PDF (content-type: {ct[:30]})"}
    except Exception as e:
        return {"status": "erro", "mensagem": f"Erro: {str(e)[:200]}"}

#!/usr/bin/env python3
"""
17 - Certidão TST CNDT (Certidão Negativa de Débitos Trabalhistas)
Captcha customizado: áudio WAV ditando letras em português + Whisper GPU
Método: Stealth Chrome + Whisper medium (100% local, zero API externa)
URL: https://cndt-certidao.tst.jus.br/inicio.faces
"""
import json
import os
import sys
import time
import tempfile
import re
from pathlib import Path
import requests
from flask import Flask, request as flask_request, jsonify

app = Flask(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────
TST_URL = "https://cndt-certidao.tst.jus.br/inicio.faces"
DISPLAY = os.environ.get("CAPTCHA_DISPLAY", ":121")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}


def log(msg):
    print(f"[TST-CNDT][{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def resolver_captcha_tst(cpf_cnpj, display=":121"):
    """Resolve TST captcha via áudio + Whisper (100% local)."""
    solver_dir = Path(__file__).parent / "infra"
    sys.path.insert(0, str(solver_dir.parent))
    from infra.tst_captcha_solver import solve_tst_captcha
    return solve_tst_captcha(cpf_cnpj, display=display)


def emitir_cndt(cpf_cnpj: str) -> dict:
    """
    Emite CNDT (Certidão Negativa de Débitos Trabalhistas) via TST.
    Resolve captcha customizado com áudio + Whisper.
    """
    digitos = ''.join(c for c in cpf_cnpj if c.isdigit())
    is_cpf = len(digitos) <= 11
    tipo = "CPF" if is_cpf else "CNPJ"

    if is_cpf and len(digitos) != 11:
        return {"status": "erro", "mensagem": f"CPF inválido: {digitos} ({len(digitos)} dígitos)"}
    if not is_cpf and len(digitos) != 14:
        return {"status": "erro", "mensagem": f"CNPJ inválido: {digitos} ({len(digitos)} dígitos)"}

    log(f"Emitindo CNDT para {tipo}: {digitos}")

    try:
        # Resolver captcha via Chrome+Whisper (retorna HTML da certidão)
        result = resolver_captcha_tst(digitos, display=DISPLAY)

        if result.get("status") != "sucesso":
            return result

        html = result.get("html", "")
        if not html:
            return {"status": "erro", "mensagem": "Certidão vazia"}

        # Analisar resultado
        if "CERTIFICA" in html or "NÃO CONSTA" in html or "N&Atilde;O CONSTA" in html or "NEGATIVA" in html.upper():
            tipo_certidao = "nada_consta"
        elif "POSITIVA" in html.upper():
            tipo_certidao = "positiva"
        elif "CONSTA" in html.upper():
            tipo_certidao = "consta"
        else:
            tipo_certidao = "verificar"

        # Extrair informações
        # Nome/Razão Social
        m_nome = re.search(r'(?:Nome|Raz[aã]o Social)[:\s]*(?:</[^>]+>\s*)?<[^>]*>([^<]+)', html, re.IGNORECASE)
        nome = m_nome.group(1).strip() if m_nome else ""

        # Número da certidão
        m_num = re.search(r'Certid[aã]o\s*(?:n[uú]mero|nº|n\.?)\s*[:.]?\s*(\d[\d/.]+)', html, re.IGNORECASE)
        numero = m_num.group(1).strip() if m_num else ""

        # Data emissão
        m_data = re.search(r'(?:emiss[aã]o|expedida em)[:\s]*(\d{2}/\d{2}/\d{4})', html, re.IGNORECASE)
        data_emissao = m_data.group(1).strip() if m_data else ""

        # Validade
        m_val = re.search(r'(?:validade|v[aá]lida at[eé])[:\s]*(\d{2}/\d{2}/\d{4})', html, re.IGNORECASE)
        validade = m_val.group(1).strip() if m_val else ""

        log(f"SUCESSO! Tipo: {tipo_certidao} | Nome: {nome} | Nº: {numero}")

        # Salvar HTML e gerar PDF
        tmpdir = tempfile.mkdtemp(prefix="tst_cndt_")
        html_path = os.path.join(tmpdir, f"cndt_{digitos}.html")
        pdf_path = os.path.join(tmpdir, f"cndt_{digitos}.pdf")

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)

        link = None
        try:
            os.system(f'wkhtmltopdf --quiet "{html_path}" "{pdf_path}" 2>/dev/null')
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 100:
                link = upload_para_tmpfiles(pdf_path)
        except:
            pass

        if not link:
            link = upload_para_tmpfiles(html_path)

        return {
            "status": "sucesso",
            "tipo_certidao": tipo_certidao,
            "nome": nome,
            "cpf_cnpj": digitos,
            "numero_certidao": numero,
            "data_emissao": data_emissao,
            "validade": validade,
            "link": link,
            "metodo": "local_audio_whisper",
        }

    except Exception as e:
        log(f"ERRO: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "erro", "mensagem": str(e)}


def upload_para_tmpfiles(caminho_arquivo):
    """Upload para tmpfiles.org (padrão Pedro)."""
    try:
        with open(caminho_arquivo, 'rb') as f:
            response = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
        if response.status_code == 200:
            link = response.json().get("data", {}).get("url")
            log(f"Upload OK: {link}")
            return link
        else:
            log(f"Upload erro status: {response.status_code}")
            return None
    except Exception as e:
        log(f"Upload erro: {e}")
        return None


# ─── Flask API ──────────────────────────────────────────────────────
@app.route("/certidao", methods=["POST"])
def api_certidao():
    data = flask_request.json or {}
    cpf = data.get("cpf")
    cnpj = data.get("cnpj")
    cpf_cnpj = cpf or cnpj

    if not cpf_cnpj:
        return jsonify({"erro": "cpf ou cnpj é obrigatório"}), 400

    try:
        resultado = emitir_cndt(cpf_cnpj)
        if resultado.get("status") == "sucesso":
            return jsonify(resultado), 200
        else:
            return jsonify(resultado), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="CNDT - Certidão Negativa de Débitos Trabalhistas (TST)")
    p.add_argument("--cpf", help="CPF para consulta")
    p.add_argument("--cnpj", help="CNPJ para consulta")
    p.add_argument("--serve", action="store_true", help="Rodar Flask API")
    p.add_argument("--port", type=int, default=5017, help="Porta Flask")
    a = p.parse_args()

    if a.serve:
        app.run(port=a.port, debug=True)
    else:
        cpf_cnpj = a.cpf or a.cnpj
        if not cpf_cnpj:
            print("Use --cpf ou --cnpj")
            sys.exit(1)
        result = emitir_cndt(cpf_cnpj)
        print(json.dumps(result, ensure_ascii=False, indent=2))

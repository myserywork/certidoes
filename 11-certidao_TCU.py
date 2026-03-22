#!/usr/bin/env python3
"""
11 - Certidão TCU (Tribunal de Contas da União) - Nada Consta
reCAPTCHA v2 com sitekey: 6LcRIUAkAAAAAGWdjhHC8mn-5A87StjjSVkn9N54
Método: Stealth Chrome + audio challenge + Whisper GPU (100% local, zero API externa)
COMPROVADO: token local obtido em ~23s (sessão anterior)
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
TCU_URL = "https://contas.tcu.gov.br/certidao/Web/Certidao/NadaConsta/home.faces"
SITEKEY = "6LcRIUAkAAAAAGWdjhHC8mn-5A87StjjSVkn9N54"
DISPLAY = os.environ.get("CAPTCHA_DISPLAY", ":121")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://contas.tcu.gov.br/certidao/Web/Certidao/NadaConsta/home.faces",
    "Origin": "https://contas.tcu.gov.br",
}


def log(msg):
    print(f"[TCU][{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def resolver_recaptcha_local(sitekey, url, display=":121"):
    """Resolve reCAPTCHA v2 via audio + Whisper (100% local)."""
    solver_dir = Path(__file__).parent / "infra"
    sys.path.insert(0, str(solver_dir.parent))
    from infra.local_captcha_solver import solve_recaptcha_v2
    return solve_recaptcha_v2(url, profile_name="tcu", display=display)


def extrair_viewstate(html):
    """Extrai javax.faces.ViewState do HTML."""
    m = re.search(r'name="javax\.faces\.ViewState"\s+value="([^"]*)"', html)
    if m:
        return m.group(1)
    m = re.search(r'id="j_id1"\s+value="([^"]*)"', html)
    if m:
        return m.group(1)
    # Fallback: qualquer ViewState
    m = re.search(r'ViewState[^>]+value="([^"]*)"', html)
    return m.group(1) if m else None


def extrair_qtd_acessos(html):
    """Extrai valor do campo qtdAcessos."""
    m = re.search(r'id="formEmitirCertidaoNadaConsta:qtdAcessos"\s+value="(\d+)"', html)
    return m.group(1) if m else "16765130"


def emitir_certidao_tcu(cpf_cnpj: str) -> dict:
    """
    Emite certidão TCU via HTTP puro + 2captcha.
    """
    digitos = ''.join(c for c in cpf_cnpj if c.isdigit())
    is_cpf = len(digitos) <= 11
    tipo = "cpf" if is_cpf else "cnpj"

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # 1. GET página inicial (pegar cookies + ViewState)
        log(f"GET página TCU para {tipo.upper()}: {digitos}")
        resp = session.get(TCU_URL, timeout=30)
        resp.raise_for_status()
        html = resp.text

        viewstate = extrair_viewstate(html)
        qtd_acessos = extrair_qtd_acessos(html)
        log(f"ViewState: {viewstate[:30]}... | qtdAcessos: {qtd_acessos}")

        if not viewstate:
            return {"status": "erro", "mensagem": "ViewState não encontrado"}

        # 2. Resolver reCAPTCHA v2 via audio + Whisper (100% local)
        token = resolver_recaptcha_local(SITEKEY, TCU_URL, display=DISPLAY)
        if not token:
            return {"status": "erro", "mensagem": "Falha ao resolver reCAPTCHA (audio+Whisper)"}

        # 3. POST formulário com token
        form_data = {
            "formEmitirCertidaoNadaConsta": "formEmitirCertidaoNadaConsta",
            "formEmitirCertidaoNadaConsta:tipoPesquisa": tipo,
            "formEmitirCertidaoNadaConsta:txtCpfOuCnpj": digitos,
            "formEmitirCertidaoNadaConsta:seCaptcha": "true",
            "formEmitirCertidaoNadaConsta:qtdAcessos": qtd_acessos,
            "g-recaptcha-response": token,
            "formEmitirCertidaoNadaConsta:btnEmitirCertidao": "Emitir Certidão",
            "javax.faces.ViewState": viewstate,
        }

        log("POST formulário com token reCAPTCHA...")
        resp = session.post(TCU_URL, data=form_data, timeout=30)
        resp.raise_for_status()
        resultado_html = resp.text

        # 4. Analisar resultado
        if "CERTIFICA" in resultado_html or "NÃO CONSTA" in resultado_html or "N&Atilde;O CONSTA" in resultado_html:
            tipo_certidao = "nada_consta"
        elif "CONSTA" in resultado_html.upper() and "NÃO CONSTA" not in resultado_html:
            tipo_certidao = "consta"
        else:
            tipo_certidao = "verificar"

        # Extrair nome do requerente
        m_nome = re.search(r'Requerente:.*?<b>([^<]+)</b>', resultado_html)
        nome = m_nome.group(1).strip() if m_nome else ""

        # Extrair código de controle
        m_codigo = re.search(r'idCodControle["\']>([^<]+)<', resultado_html)
        codigo = m_codigo.group(1).strip() if m_codigo else ""

        log(f"SUCESSO! Tipo: {tipo_certidao} | Nome: {nome} | Código: {codigo}")

        # 5. Salvar HTML como arquivo e gerar PDF via wkhtmltopdf (se disponível)
        tmpdir = tempfile.mkdtemp(prefix="tcu_")
        html_path = os.path.join(tmpdir, f"certidao_tcu_{digitos}.html")
        pdf_path = os.path.join(tmpdir, f"certidao_tcu_{digitos}.pdf")

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(resultado_html)

        # Tentar gerar PDF
        link = None
        try:
            os.system(f'wkhtmltopdf --quiet "{html_path}" "{pdf_path}" 2>/dev/null')
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 100:
                link = upload_para_tmpfiles(pdf_path)
        except:
            pass

        # Se PDF falhou, upload HTML
        if not link:
            link = upload_para_tmpfiles(html_path)

        return {
            "status": "sucesso",
            "tipo_certidao": tipo_certidao,
            "nome": nome,
            "cpf_cnpj": digitos,
            "codigo_controle": codigo,
            "link": link,
            "resultado": resultado_html[:1000],
        }

    except requests.exceptions.RequestException as e:
        log(f"ERRO HTTP: {e}")
        return {"status": "erro", "mensagem": str(e)}
    except Exception as e:
        log(f"ERRO: {e}")
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
        resultado = emitir_certidao_tcu(cpf_cnpj)

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
    p = argparse.ArgumentParser(description="Certidão TCU - Nada Consta")
    p.add_argument("--cpf", help="CPF para consulta")
    p.add_argument("--cnpj", help="CNPJ para consulta")
    p.add_argument("--serve", action="store_true", help="Rodar Flask API")
    p.add_argument("--port", type=int, default=5011, help="Porta Flask")
    a = p.parse_args()

    if a.serve:
        app.run(port=a.port, debug=True)
    else:
        cpf_cnpj = a.cpf or a.cnpj
        if not cpf_cnpj:
            print("Use --cpf ou --cnpj")
            sys.exit(1)
        result = emitir_certidao_tcu(cpf_cnpj)
        print(json.dumps(result, ensure_ascii=False, indent=2))

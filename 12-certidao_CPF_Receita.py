#!/usr/bin/env python3
"""
12 - Consulta Situação Cadastral CPF - Receita Federal
hCaptcha com sitekey: 53be2ee7-5efc-494e-a3ba-c9258649c070
Método: Stealth Chrome + CLIP visual solver (100% local, zero API externa)
Campos: CPF + Data de Nascimento
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
CPF_URL = "https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/consultapublica.asp"
CPF_POST_URL = "https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/ConsultaPublicaExibir.asp"
HCAPTCHA_SITEKEY = "53be2ee7-5efc-494e-a3ba-c9258649c070"
DISPLAY = os.environ.get("CAPTCHA_DISPLAY", ":121")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
}


def log(msg):
    print(f"[CPF-RF][{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def resolver_hcaptcha_local(url, display=":121"):
    """Resolve hCaptcha: tenta 2captcha primeiro, fallback CLIP local."""
    solver_dir = Path(__file__).parent / "infra"
    sys.path.insert(0, str(solver_dir.parent))

    try:
        from infra.twocaptcha_solver import solve_hcaptcha as solve_2captcha
        token = solve_2captcha(HCAPTCHA_SITEKEY, url)
        if token:
            log("hCaptcha resolvido via 2captcha")
            return token
    except Exception as e:
        log(f"2captcha falhou ({e}), tentando CLIP local...")

    from infra.hcaptcha_solver import solve_hcaptcha
    return solve_hcaptcha(url, display=display)


def formatar_cpf(cpf_digits):
    """Formata CPF: 12345678900 -> 123.456.789-00"""
    d = cpf_digits.zfill(11)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def formatar_data(data_str):
    """Garante formato dd/mm/aaaa."""
    # Aceita: ddmmaaaa, dd/mm/aaaa, dd-mm-aaaa
    d = ''.join(c for c in data_str if c.isdigit())
    if len(d) == 8:
        return f"{d[:2]}/{d[2:4]}/{d[4:]}"
    return data_str


def consultar_cpf(cpf: str, data_nascimento: str) -> dict:
    """
    Consulta situação cadastral do CPF na Receita Federal.
    cpf: apenas dígitos ou formatado
    data_nascimento: dd/mm/aaaa
    """
    digitos = ''.join(c for c in cpf if c.isdigit())
    if len(digitos) != 11:
        return {"status": "erro", "mensagem": f"CPF inválido: {digitos} ({len(digitos)} dígitos)"}

    cpf_formatado = formatar_cpf(digitos)
    data_fmt = formatar_data(data_nascimento)

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # 1. GET página inicial (cookies)
        log(f"GET página CPF para: {cpf_formatado}")
        resp = session.get(CPF_URL, timeout=30)
        resp.raise_for_status()

        # 2. Resolver hCaptcha via CLIP visual (100% local)
        token = resolver_hcaptcha_local(CPF_URL, display=DISPLAY)
        if not token:
            return {"status": "erro", "mensagem": "Falha ao resolver hCaptcha (CLIP visual)"}

        # 3. POST formulário
        form_data = {
            "txtCPF": cpf_formatado,
            "txtDataNascimento": data_fmt,
            "idCheckedReCaptcha": "true",
            "h-captcha-response": token,
            "g-recaptcha-response": token,
            "Enviar": "Consultar",
        }

        log("POST formulário com token hCaptcha...")
        resp = session.post(
            CPF_POST_URL,
            data=form_data,
            headers={
                **HEADERS,
                "Referer": CPF_URL,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30,
            allow_redirects=True,
        )

        # Decodificar ISO-8859-1
        resultado_html = resp.content.decode("iso-8859-1", errors="replace")

        # 4. Verificar se houve erro (redirect Error=5 = captcha falhou)
        if "Error=" in resp.url or "Error=" in resultado_html:
            m_err = re.search(r'Error=(\d+)', resp.url or resultado_html)
            err_code = m_err.group(1) if m_err else "?"
            log(f"ERRO: Receita retornou Error={err_code}")
            return {"status": "erro", "mensagem": f"Receita retornou erro {err_code} (captcha rejeitado ou dados inválidos)"}

        # 5. Extrair informações do resultado
        # Situação cadastral
        m_situacao = re.search(r'Situa[çc][aã]o\s*Cadastral[:\s]*</span>\s*<[^>]*>([^<]+)', resultado_html, re.IGNORECASE)
        if not m_situacao:
            m_situacao = re.search(r'Situa..o Cadastral[:\s]*<[^>]*>([^<]+)', resultado_html)
        situacao = m_situacao.group(1).strip() if m_situacao else ""

        # Nome
        m_nome = re.search(r'Nome[:\s]*</span>\s*<[^>]*>([^<]+)', resultado_html, re.IGNORECASE)
        if not m_nome:
            m_nome = re.search(r'Nome[:\s]*<[^>]*>([^<]+)', resultado_html)
        nome = m_nome.group(1).strip() if m_nome else ""

        # Data de inscrição
        m_inscricao = re.search(r'Inscri[çc][aã]o[:\s]*</span>\s*<[^>]*>([^<]+)', resultado_html, re.IGNORECASE)
        data_inscricao = m_inscricao.group(1).strip() if m_inscricao else ""

        # Digito verificador / comprovante
        m_digito = re.search(r'gito\s*Verificador[:\s]*</span>\s*<[^>]*>([^<]+)', resultado_html, re.IGNORECASE)
        digito_verificador = m_digito.group(1).strip() if m_digito else ""

        if situacao or nome:
            log(f"SUCESSO! Nome: {nome} | Situação: {situacao}")

            # Salvar HTML e gerar PDF
            tmpdir = tempfile.mkdtemp(prefix="cpf_rf_")
            html_path = os.path.join(tmpdir, f"cpf_{digitos}.html")
            pdf_path = os.path.join(tmpdir, f"cpf_{digitos}.pdf")

            with open(html_path, "w", encoding="utf-8") as f:
                f.write(resultado_html)

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
                "cpf": cpf_formatado,
                "nome": nome,
                "situacao_cadastral": situacao,
                "data_inscricao": data_inscricao,
                "digito_verificador": digito_verificador,
                "link": link,
            }
        else:
            # Pode ser erro ou página vazia
            log("Resultado sem dados extraíveis")
            # Salvar pra debug
            debug_path = os.path.join(tempfile.gettempdir(), "cpf_rf_debug.html")
            with open(debug_path, "w") as f:
                f.write(resultado_html)
            return {
                "status": "erro",
                "mensagem": f"Sem dados no resultado (ver {debug_path})",
                "url_final": resp.url,
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
    data_nasc = data.get("data_nascimento") or data.get("nascimento")

    if not cpf:
        return jsonify({"erro": "cpf é obrigatório"}), 400
    if not data_nasc:
        return jsonify({"erro": "data_nascimento é obrigatório (dd/mm/aaaa)"}), 400

    try:
        resultado = consultar_cpf(cpf, data_nasc)

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
    p = argparse.ArgumentParser(description="Consulta Situação Cadastral CPF - Receita Federal")
    p.add_argument("--cpf", help="CPF para consulta", required=False)
    p.add_argument("--nascimento", help="Data de nascimento (dd/mm/aaaa)", required=False)
    p.add_argument("--serve", action="store_true", help="Rodar Flask API")
    p.add_argument("--port", type=int, default=5012, help="Porta Flask")
    a = p.parse_args()

    if a.serve:
        app.run(port=a.port, debug=True)
    else:
        if not a.cpf or not a.nascimento:
            print("Use --cpf e --nascimento, ou --serve para API")
            sys.exit(1)
        result = consultar_cpf(a.cpf, a.nascimento)
        print(json.dumps(result, ensure_ascii=False, indent=2))

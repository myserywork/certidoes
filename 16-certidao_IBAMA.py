#!/usr/bin/env python3
"""
16 - Certidão Negativa de Débito IBAMA
reCAPTCHA Enterprise (invisible/score-based)
sitekey: 6Ld2bNsrAAAAAML-kvSg-Yy3VwoXvxkr3Ymgq2t7
Método: Stealth Chrome enterprise.execute() (100% local, zero API externa)
Sistema: FormDin3 (PHP legado) - POST com formDinAcao
"""
import json
import os
import sys
import time
import tempfile
import re
import subprocess
import platform
from pathlib import Path
import requests
from flask import Flask, request as flask_request, jsonify

app = Flask(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────
IBAMA_BASE = "https://servicos.ibama.gov.br/sicafiext/sistema.php"
SITEKEY = "6Ld2bNsrAAAAAML-kvSg-Yy3VwoXvxkr3Ymgq2t7"
SOLVER_JS = Path(__file__).parent / "infra" / "recaptcha_enterprise_solver.js"
DISPLAY = os.environ.get("CAPTCHA_DISPLAY", ":121")

# PostNav JS to reach certidão module
POST_NAV_JS = "document.querySelector('input[name=\"modulo\"]').value='sisarr/cons_emitir_certidao'; document.forms['menuweb_submit'].submit();"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
}

# Namespaces para rotação em caso de bloqueio
NAMESPACES = [""] if platform.system() == "Windows" else ["", "ns_t0", "ns_t1", "ns_t2", "ns_t3", "ns_t4"]
MAX_RETRIES = 6


def log(msg):
    print(f"[IBAMA][{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def resolver_recaptcha_local(sitekey, url, timeout=45):
    """Resolve reCAPTCHA Enterprise: tenta 2captcha primeiro, fallback stealth."""
    # Tentar 2captcha
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from infra.twocaptcha_solver import solve_recaptcha_enterprise
        token = solve_recaptcha_enterprise(sitekey, url, action="submit")
        if token:
            log("reCAPTCHA Enterprise resolvido via 2captcha")
            return token
    except Exception as e:
        log(f"2captcha falhou ({e}), tentando stealth local...")

    # Fallback: stealth local
    for attempt in range(1, MAX_RETRIES + 1):
        ns_idx = (attempt - 1) % len(NAMESPACES)
        ns = NAMESPACES[ns_idx]
        ns_label = ns or "host"

        log(f"[Tentativa {attempt}/{MAX_RETRIES}] NS={ns_label}")

        _home = os.environ.get("HOME", "/root")
        _node_path = os.environ.get("NODE_PATH", "/root/node_modules")
        if ns and platform.system() != "Windows":
            cmd = [
                "sudo", "-n", "ip", "netns", "exec", ns,
                "env", f"DISPLAY={DISPLAY}", f"HOME={_home}",
                f"NODE_PATH={_node_path}",
                "node", str(SOLVER_JS), url, sitekey, POST_NAV_JS, "submit",
            ]
        else:
            cmd = ["node", str(SOLVER_JS), url, sitekey, POST_NAV_JS, "submit"]

        env = os.environ.copy()
        env["DISPLAY"] = DISPLAY
        env["HOME"] = os.environ.get("HOME", "/root")
        env["NODE_PATH"] = os.environ.get("NODE_PATH", "/root/node_modules")

        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=timeout, env=env, cwd=os.environ.get("HOME", os.environ.get("USERPROFILE", "."))
            )
            stdout = proc.stdout.decode().strip()
            stderr = proc.stderr.decode(errors="replace")

            for line in stderr.strip().split("\n"):
                if line.strip():
                    log(f"  {line.strip()}")

            if stdout:
                for line in stdout.strip().split("\n"):
                    try:
                        msg = json.loads(line)
                        if msg.get("status") == "solved" and msg.get("token"):
                            token = msg["token"]
                            log(f"Token obtido ({len(token)} chars) via {ns_label}")
                            return token
                    except json.JSONDecodeError:
                        continue

        except subprocess.TimeoutExpired:
            log(f"[{ns_label}] Timeout ({timeout}s)")
        except Exception as e:
            log(f"[{ns_label}] Erro: {e}")

        delay = min(attempt, 3)
        log(f"Falhou via {ns_label}, rotacionando em {delay}s...")
        time.sleep(delay)

    log(f"TODAS {MAX_RETRIES} tentativas falharam!")
    return None


def formatar_cpf_cnpj(digitos):
    """Formata CPF/CNPJ com pontuação."""
    if len(digitos) == 11:
        return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
    elif len(digitos) == 14:
        return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"
    return digitos


def emitir_certidao_ibama(cpf_cnpj: str) -> dict:
    """Emite certidão negativa de débito do IBAMA."""
    digitos = ''.join(c for c in cpf_cnpj if c.isdigit())
    formatado = formatar_cpf_cnpj(digitos)

    session = requests.Session()
    session.verify = False  # IBAMA tem SSL inconsistente
    session.headers.update(HEADERS)

    try:
        # 1. GET página inicial (cookies + sessão)
        log(f"Acessando IBAMA para: {formatado}")
        resp = session.get(IBAMA_BASE, timeout=30)
        resp.raise_for_status()

        # 2. Navegar para módulo de certidão (POST com modulo)
        log("Navegando para formulário de certidão...")
        resp = session.post(IBAMA_BASE, data={
            "modulo": "sisarr/cons_emitir_certidao",
        }, headers={
            **HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": IBAMA_BASE,
        }, timeout=30)
        resp.raise_for_status()

        # 3. Resolver reCAPTCHA Enterprise (100% local)
        token = resolver_recaptcha_local(SITEKEY, IBAMA_BASE)
        if not token:
            return {"status": "erro", "mensagem": "Falha ao resolver reCAPTCHA Enterprise"}

        # 4. POST formulário de pesquisa com CPF/CNPJ + reCAPTCHA token
        log(f"Submetendo pesquisa: {formatado}")
        form_data = {
            "modulo": "sisarr/cons_emitir_certidao",
            "formDinAcao": "Pesquisar",
            "formDinPosVScroll": "",
            "formDinPosHScroll": "",
            "formDinAba": "aba01",
            "p_num_cpf_cnpj": formatado,
            "g-recaptcha-response": token,
        }

        resp = session.post(IBAMA_BASE, data=form_data, headers={
            **HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": IBAMA_BASE,
        }, timeout=30)

        resultado_html = resp.content.decode("iso-8859-1", errors="replace")

        # 5. Analisar resultado
        # Verificar se tem certidão (iframe ou link PDF)
        m_iframe = re.search(r'src="([^"]*certidao[^"]*)"', resultado_html, re.IGNORECASE)
        m_pdf = re.search(r'href="([^"]*\.pdf[^"]*)"', resultado_html, re.IGNORECASE)
        m_nada = re.search(r'(n[aã]o\s+consta|nada\s+consta|negativa)', resultado_html, re.IGNORECASE)
        m_erro = re.search(r'(erro|invalido|inv[aá]lido|captcha)', resultado_html, re.IGNORECASE)

        # Verificar se foi pra tela de resultado com gride (tabela de resultados)
        has_result = 'formDinAbaDados2' in resultado_html or 'htmlIframe' in resultado_html

        log(f"Resultado: {len(resultado_html)} bytes, iframe={bool(m_iframe)}, pdf={bool(m_pdf)}, nada_consta={bool(m_nada)}, has_result={has_result}")

        # Salvar resultado HTML
        tmpdir = tempfile.mkdtemp(prefix="ibama_")
        html_path = os.path.join(tmpdir, f"ibama_{digitos}.html")
        pdf_path = os.path.join(tmpdir, f"certidao_ibama_{digitos}.pdf")

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(resultado_html)

        # Se há iframe com certidão, baixar
        link = None
        if m_iframe:
            iframe_url = m_iframe.group(1)
            if not iframe_url.startswith("http"):
                iframe_url = f"https://servicos.ibama.gov.br/sicafiext/{iframe_url}"
            log(f"Baixando certidão do iframe: {iframe_url}")
            try:
                resp_pdf = session.get(iframe_url, timeout=30)
                if resp_pdf.status_code == 200 and len(resp_pdf.content) > 100:
                    with open(pdf_path, "wb") as f:
                        f.write(resp_pdf.content)
                    link = upload_para_tmpfiles(pdf_path)
            except Exception as e:
                log(f"Erro baixando iframe: {e}")

        if not link:
            # Tentar gerar PDF do HTML
            try:
                os.system(f'wkhtmltopdf --quiet "{html_path}" "{pdf_path}" 2>/dev/null')
                if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 100:
                    link = upload_para_tmpfiles(pdf_path)
            except:
                pass

        if not link:
            link = upload_para_tmpfiles(html_path)

        tipo = "nada_consta" if m_nada else "verificar"

        return {
            "status": "sucesso" if has_result or m_nada else "parcial",
            "tipo_certidao": tipo,
            "cpf_cnpj": formatado,
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
        resultado = emitir_certidao_ibama(cpf_cnpj)

        if "sucesso" in resultado.get("status", "") or "parcial" in resultado.get("status", ""):
            return jsonify(resultado), 200
        else:
            return jsonify(resultado), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Certidão Negativa de Débito IBAMA")
    p.add_argument("--cpf", help="CPF para consulta")
    p.add_argument("--cnpj", help="CNPJ para consulta")
    p.add_argument("--serve", action="store_true", help="Rodar Flask API")
    p.add_argument("--port", type=int, default=5016, help="Porta Flask")
    a = p.parse_args()

    if a.serve:
        app.run(port=a.port, debug=True)
    else:
        cpf_cnpj = a.cpf or a.cnpj
        if not cpf_cnpj:
            print("Use --cpf ou --cnpj")
            sys.exit(1)
        result = emitir_certidao_ibama(cpf_cnpj)
        print(json.dumps(result, ensure_ascii=False, indent=2))

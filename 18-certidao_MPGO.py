#!/usr/bin/env python3
"""
18 - Certidão MPGO (Ministério Público do Estado de Goiás)
reCAPTCHA v2 com sitekey: 6LeFH8QUAAAAAN9aRSQ2IpZ8vYqK07ui1o5uek7G
Método: Stealth Chrome + audio challenge + Whisper GPU (100% local)
URL: https://www.mpgo.mp.br/certidao
Retorna: PDF da certidão
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
MPGO_URL = "https://www.mpgo.mp.br/certidao"
MPGO_EMIT_URL = "https://www.mpgo.mp.br/certidao/emitir_certidao"
SITEKEY = "6LeFH8QUAAAAAN9aRSQ2IpZ8vYqK07ui1o5uek7G"
DISPLAY = os.environ.get("CAPTCHA_DISPLAY", ":121")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}


def log(msg):
    print(f"[MPGO][{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def resolver_recaptcha_local(url, display=":121"):
    """Resolve reCAPTCHA v2 via stealth auto-solve + audio fallback (100% local)."""
    import subprocess
    
    solver_js = Path(__file__).parent / "infra" / "mpgo_recaptcha_solver.js"
    env = os.environ.copy()
    env["DISPLAY"] = display
    env["NODE_PATH"] = os.environ.get("NODE_PATH", "/root/node_modules")
    env["HOME"] = os.environ.get("HOME", "/root")
    
    try:
        proc = subprocess.Popen(
            ["node", str(solver_js)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, cwd=os.environ.get("HOME", "/root"),
        )
        
        import json as _json
        start = time.time()
        result_data = None
        
        while time.time() - start < 90:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
                continue
            
            msg = _json.loads(line.decode().strip())
            status = msg.get("status", "")
            
            if status in ("solved", "auto_solved"):
                result_data = msg
                break
            
            elif status == "audio_challenge":
                # Whisper transcribe
                audio_file = msg.get("audio_file", "")
                log(f"Audio challenge: {audio_file}")
                r = subprocess.run(
                    ["python3", "-c", f"""
import whisper, re
m = whisper.load_model("base", device="cuda")
r = m.transcribe("{audio_file}", language="en", fp16=True)
t = re.sub(r'[^a-z0-9 ]', '', r["text"].strip().lower()).strip()
print(t)
"""],
                    capture_output=True, timeout=30, cwd=os.environ.get("HOME", "/root"),
                )
                answer = r.stdout.decode().strip()
                log(f"Whisper answer: '{answer}'")
                proc.stdin.write(_json.dumps({"answer": answer}).encode() + b"\n")
                proc.stdin.flush()
            
            elif status in ("error", "failed"):
                log(f"Solver error: {msg.get('error', '?')}")
                break
        
        try:
            proc.kill()
        except:
            pass
        
        if result_data:
            return result_data.get("token", ""), result_data.get("csrf", ""), result_data.get("cookies", "")
        return "", "", ""
    
    except Exception as e:
        log(f"Solver error: {e}")
        return "", "", ""


def formatar_cpf_cnpj(digitos):
    """Formata CPF ou CNPJ."""
    d = digitos
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    elif len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return d


def emitir_certidao_mpgo(cpf_cnpj: str) -> dict:
    """Emite certidão do MPGO."""
    digitos = ''.join(c for c in cpf_cnpj if c.isdigit())
    is_cpf = len(digitos) <= 11
    tipo = "CPF" if is_cpf else "CNPJ"

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # 1. GET página inicial (cookies + CSRF token)
        log(f"GET página MPGO para {tipo}: {digitos}")
        resp = session.get(MPGO_URL, timeout=30)
        resp.raise_for_status()
        html = resp.text

        # Extrair CSRF token (Rails authenticity_token)
        m_csrf = re.search(r'name="authenticity_token"\s+value="([^"]+)"', html)
        if not m_csrf:
            m_csrf = re.search(r'csrf-token"\s+content="([^"]+)"', html)
        csrf_token = m_csrf.group(1) if m_csrf else ""
        log(f"CSRF token: {csrf_token[:40]}...")

        if not csrf_token:
            return {"status": "erro", "mensagem": "CSRF token não encontrado"}

        # 2. Resolver reCAPTCHA v2: tenta 2captcha, fallback stealth
        token = None
        browser_csrf = ""
        browser_cookies = ""

        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from infra.twocaptcha_solver import solve_recaptcha_v2
            token = solve_recaptcha_v2(SITEKEY, MPGO_URL)
            if token:
                log("reCAPTCHA resolvido via 2captcha")
        except Exception as e:
            log(f"2captcha falhou ({e}), tentando stealth...")

        if not token:
            token, browser_csrf, browser_cookies = resolver_recaptcha_local(MPGO_URL, display=DISPLAY)

        if not token:
            return {"status": "erro", "mensagem": "Falha ao resolver reCAPTCHA"}
        
        # Use browser CSRF if available (fresher than from initial GET)
        if browser_csrf:
            csrf_token = browser_csrf
        
        # Set browser cookies on session
        if browser_cookies:
            for cookie_str in browser_cookies.split("; "):
                if "=" in cookie_str:
                    name, val = cookie_str.split("=", 1)
                    session.cookies.set(name.strip(), val.strip())

        # 3. POST para emitir certidão
        cpf_cnpj_fmt = formatar_cpf_cnpj(digitos)
        form_data = {
            "utf8": "✓",
            "authenticity_token": csrf_token,
            "cpf_cnpj": cpf_cnpj_fmt,
            "g-recaptcha-response": token,
        }

        log(f"POST emitir certidão para {cpf_cnpj_fmt}...")
        resp = session.post(
            MPGO_EMIT_URL,
            data=form_data,
            headers={
                **HEADERS,
                "Referer": MPGO_URL,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30,
            allow_redirects=True,
        )

        # 4. Verificar se recebeu PDF
        content_type = resp.headers.get("Content-Type", "")
        log(f"Response: {resp.status_code} | Content-Type: {content_type} | Size: {len(resp.content)}")

        if "pdf" in content_type.lower() or resp.content[:5] == b"%PDF-":
            # Recebeu PDF diretamente
            tmpdir = tempfile.mkdtemp(prefix="mpgo_")
            pdf_path = os.path.join(tmpdir, f"certidao_mpgo_{digitos}.pdf")
            with open(pdf_path, "wb") as f:
                f.write(resp.content)
            log(f"PDF salvo: {pdf_path} ({len(resp.content)} bytes)")

            link = upload_para_tmpfiles(pdf_path)

            return {
                "status": "sucesso",
                "tipo_certidao": "certidao_mpgo",
                "cpf_cnpj": digitos,
                "link": link,
                "pdf_size": len(resp.content),
                "metodo": "local_audio_whisper",
            }

        # Se não recebeu PDF, verificar resposta
        resultado = resp.text
        if "cookie" in content_type.lower():
            # fileDownload jQuery plugin response
            log("fileDownload cookie response — certidão pode ter sido emitida como PDF")

        # Verificar se é HTML com erro
        if resp.status_code != 200:
            return {
                "status": "erro",
                "mensagem": f"HTTP {resp.status_code}: {resultado[:500]}",
            }

        # Pode ser HTML com mensagem de erro
        if "erro" in resultado.lower() or "error" in resultado.lower():
            m_err = re.search(r'alert\(["\'](.+?)["\']\)', resultado)
            err_msg = m_err.group(1) if m_err else resultado[:500]
            return {"status": "erro", "mensagem": err_msg}

        # Retorno desconhecido
        tmpdir = tempfile.mkdtemp(prefix="mpgo_")
        html_path = os.path.join(tmpdir, f"mpgo_{digitos}.html")
        with open(html_path, "w") as f:
            f.write(resultado)

        return {
            "status": "parcial",
            "mensagem": f"Resposta não-PDF ({content_type})",
            "cpf_cnpj": digitos,
            "response_size": len(resultado),
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
        resultado = emitir_certidao_mpgo(cpf_cnpj)
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
    p = argparse.ArgumentParser(description="Certidão MPGO (Ministério Público de Goiás)")
    p.add_argument("--cpf", help="CPF para consulta")
    p.add_argument("--cnpj", help="CNPJ para consulta")
    p.add_argument("--serve", action="store_true", help="Rodar Flask API")
    p.add_argument("--port", type=int, default=5018, help="Porta Flask")
    a = p.parse_args()

    if a.serve:
        app.run(port=a.port, debug=True)
    else:
        cpf_cnpj = a.cpf or a.cnpj
        if not cpf_cnpj:
            print("Use --cpf ou --cnpj")
            sys.exit(1)
        result = emitir_certidao_mpgo(cpf_cnpj)
        print(json.dumps(result, ensure_ascii=False, indent=2))

#!/usr/bin/env python3
"""
12 - Consulta Situacao Cadastral CPF - Receita Federal
hCaptcha com sitekey: 53be2ee7-5efc-494e-a3ba-c9258649c070
Metodo: Stealth Chrome + CLIP visual solver — tudo no mesmo browser (100% local)
Campos: CPF + Data de Nascimento
"""
import json
import os
import sys
import time
import tempfile
import re
import subprocess
from pathlib import Path
import requests
from flask import Flask, request as flask_request, jsonify

app = Flask(__name__)

# --- CONFIG ---
DISPLAY = os.environ.get("CAPTCHA_DISPLAY", ":121")
SOLVER_JS = Path(__file__).parent / "infra" / "cpf_receita_full_solver.js"

# Mapeamento de display para namespaces (X11 via TCP no WSL2)
NS_DISPLAY_MAP = {
    "ns_t0": "10.200.0.1:121.0",
    "ns_t1": "10.200.1.1:121.0",
    "ns_t2": "10.200.2.1:121.0",
    "ns_t3": "10.200.3.1:121.0",
    "ns_t4": "10.200.4.1:121.0",
}

NAMESPACES = ["", "ns_t0", "ns_t1", "ns_t2", "ns_t3", "ns_t4"]
MAX_RETRIES = 6


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[CPF-RF][{ts}] {msg}", file=sys.stderr, flush=True)


def formatar_cpf(cpf_digits):
    d = cpf_digits.zfill(11)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def formatar_data(data_str):
    d = "".join(c for c in data_str if c.isdigit())
    if len(d) == 8:
        return f"{d[:2]}/{d[2:4]}/{d[4:]}"
    return data_str


# --- CLIP classifier ---
_clip_loaded = False


def _ensure_clip():
    global _clip_loaded
    if not _clip_loaded:
        sys.path.insert(0, str(Path(__file__).parent))
        _clip_loaded = True


def classify_images_clip(prompt, images, example=""):
    _ensure_clip()
    from infra.hcaptcha_solver import classify_images_clip as _classify
    return _classify(prompt, images, example)


def consultar_cpf_single(cpf_fmt, data_fmt, display, ns=""):
    ns_label = ns or "host"
    log(f"[{ns_label}] Iniciando consulta {cpf_fmt}...")

    env = os.environ.copy()
    env["DISPLAY"] = display
    env["HOME"] = "/root"
    env["NODE_PATH"] = "/root/node_modules"

    if ns:
        cmd = [
            "ip", "netns", "exec", ns,
            "env", f"DISPLAY={NS_DISPLAY_MAP.get(ns, display)}", "HOME=/root",
            "NODE_PATH=/root/node_modules",
            "node", str(SOLVER_JS), cpf_fmt, data_fmt,
        ]
    else:
        cmd = ["node", str(SOLVER_JS), cpf_fmt, data_fmt]

    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, cwd="/root",
        )

        start = time.time()
        result = None

        while time.time() - start < 180:
            try:
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                    continue

                msg = json.loads(line.decode().strip())
                status = msg.get("status", "")

                if status == "challenge":
                    prompt = msg.get("prompt", "")
                    images = msg.get("images", [])
                    example = msg.get("example", "")
                    round_num = msg.get("round", 1)
                    log(f"[{ns_label}] Round {round_num} -- {repr(prompt)}, {len(images)} imgs")

                    clicks = classify_images_clip(prompt, images, example)
                    response = json.dumps({"clicks": clicks}) + "\n"
                    proc.stdin.write(response.encode())
                    proc.stdin.flush()
                    log(f"[{ns_label}] Sent clicks: {clicks}")

                elif status == "sucesso":
                    log(f"[{ns_label}] SUCESSO: {msg.get('nome', '')} | {msg.get('situacao', '')}")
                    result = msg
                    break

                elif status == "erro":
                    log(f"[{ns_label}] ERRO: {msg.get('error', '?')}")
                    result = msg
                    break

            except json.JSONDecodeError:
                continue
            except Exception as e:
                log(f"[{ns_label}] Read error: {e}")
                break

        try:
            proc.kill()
        except Exception:
            pass

        try:
            stderr = proc.stderr.read().decode(errors="replace")
            for sline in stderr.strip().split("\n"):
                if sline.strip():
                    log(f"  {sline.strip()}")
        except Exception:
            pass

        return result

    except Exception as e:
        log(f"[{ns_label}] Error: {e}")
        return None


def upload_para_tmpfiles(caminho_arquivo):
    try:
        with open(caminho_arquivo, "rb") as f:
            response = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": f})
        if response.status_code == 200:
            link = response.json().get("data", {}).get("url")
            log(f"Upload OK: {link}")
            return link
        return None
    except Exception as e:
        log(f"Upload erro: {e}")
        return None


def consultar_cpf(cpf, data_nascimento):
    digitos = "".join(c for c in cpf if c.isdigit())
    if len(digitos) != 11:
        return {"status": "erro", "mensagem": f"CPF invalido: {digitos} ({len(digitos)} digitos)"}

    cpf_formatado = formatar_cpf(digitos)
    data_fmt = formatar_data(data_nascimento)

    for attempt in range(1, MAX_RETRIES + 1):
        ns = NAMESPACES[(attempt - 1) % len(NAMESPACES)]
        ns_label = ns or "host"
        log(f"[Tentativa {attempt}/{MAX_RETRIES}] NS={ns_label}")

        result = consultar_cpf_single(cpf_formatado, data_fmt, DISPLAY, ns)

        if result and result.get("status") == "sucesso":
            nome = result.get("nome", "")
            situacao = result.get("situacao", "")
            html_path = result.get("html_path", "")

            link = None
            if html_path and os.path.exists(html_path):
                pdf_path = html_path.replace(".html", ".pdf")
                try:
                    os.system(f'wkhtmltopdf --quiet "{html_path}" "{pdf_path}" 2>/dev/null')
                    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 100:
                        link = upload_para_tmpfiles(pdf_path)
                except Exception:
                    pass
                if not link:
                    link = upload_para_tmpfiles(html_path)

            return {
                "status": "sucesso",
                "cpf": cpf_formatado,
                "nome": nome,
                "situacao_cadastral": situacao,
                "data_inscricao": result.get("inscricao", ""),
                "digito_verificador": result.get("digito", ""),
                "link": link,
                "metodo": "browser_clip_visual",
            }

        if result and result.get("status") == "erro":
            error = result.get("error", "")
            if "receita_error" in error:
                log(f"Receita rejeitou (tentativa {attempt}), rotacionando...")

        try:
            os.system("pkill -f 'chrome.*cpf_receita' 2>/dev/null")
        except Exception:
            pass
        time.sleep(2)

    return {"status": "erro", "mensagem": f"Falha apos {MAX_RETRIES} tentativas"}


# --- Flask API ---
@app.route("/certidao", methods=["POST"])
def api_certidao():
    data = flask_request.json or {}
    cpf = data.get("cpf")
    data_nasc = data.get("data_nascimento") or data.get("nascimento")

    if not cpf:
        return jsonify({"erro": "cpf e obrigatorio"}), 400
    if not data_nasc:
        return jsonify({"erro": "data_nascimento e obrigatorio (dd/mm/aaaa)"}), 400

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
    p = argparse.ArgumentParser(description="Consulta Situacao Cadastral CPF - Receita Federal")
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

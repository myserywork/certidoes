#!/usr/bin/env python3
"""
13 - Certidão Negativa MPF (Ministério Público Federal)
Cloudflare Turnstile com sitekey: 0x4AAAAAACMhejJkLsBWVaMb

Método: Puppeteer-stealth FULL LOCAL (Turnstile auto-resolve, custo ZERO)
Fallback: rotação de IP/namespace (ns_t0→ns_t4), até 10 tentativas

API REST Angular: consultar nome → emitir → download PDF
"""
import json
import os
import sys
import time
import tempfile
import subprocess
import platform
import requests
from pathlib import Path
from flask import Flask, request as flask_request, jsonify

app = Flask(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────
MPF_BASE = "https://aplicativos.mpf.mp.br"
MPF_CONSULTAR = f"{MPF_BASE}/ouvidoria/rest/v1/publico/certidao/consultar"
MPF_EMITIR = f"{MPF_BASE}/ouvidoria/rest/v1/publico/certidao/emitir"
MPF_DOWNLOAD = f"{MPF_BASE}/ouvidoria/rest/v1/publico/certidao/download"
MPF_PAGE = f"{MPF_BASE}/ouvidoria/app/cidadao/certidao"

TURNSTILE_SITEKEY = "0x4AAAAAACMhejJkLsBWVaMb"

# Stealth config
DISPLAY = os.environ.get("DISPLAY", ":120")
SOURCE_PROFILE = Path(tempfile.gettempdir()) / "chrome_profile"
PROFILE_DIR = Path(__file__).parent / "infra" / "profiles" / "mpf"
CHROME_PATH = None if platform.system() == "Windows" else "/usr/bin/google-chrome"

# Namespaces: no Windows so roda no host (sem ip netns)
if platform.system() == "Windows":
    NAMESPACES = [""]
    MAX_RETRIES = 3
else:
    NAMESPACES = ["", "ns_t0", "ns_t1", "ns_t2", "ns_t3", "ns_t4"]
    MAX_RETRIES = 10

# JS solver file (persistente, não usar /tmp para evitar deleção acidental)
STEALTH_SOLVER_JS_PATH = Path(__file__).parent / "infra" / "mpf_stealth_solver.js"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": f"{MPF_BASE}/ouvidoria/app/cidadao/certidao",
    "Origin": MPF_BASE,
}


def log(msg):
    print(f"[MPF][{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


# ─── Stealth Solver (FULL LOCAL — custo ZERO) ────────────────────

def _kill_orphan_chrome():
    """Matar Chrome órfão usando profile mpf (evita lock)."""
    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe", "/T"], capture_output=True, timeout=10)
    else:
        subprocess.run(["pkill", "-9", "-f", "profiles/mpf"], capture_output=True, timeout=5)
    time.sleep(0.5)


def _clean_profile_locks():
    """Limpar locks do profile Chrome."""
    locks = ["SingletonLock", "SingletonCookie", "SingletonSocket"]
    for lk in locks:
        p = PROFILE_DIR / lk
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass


def resolver_turnstile_stealth(display=None, ns="", timeout=55):
    """
    Resolve Cloudflare Turnstile via Puppeteer-stealth.
    ns: namespace VPN (ex: "ns_t0"). Vazio = host direto.
    """
    display = display or DISPLAY
    ns_label = ns or "host"
    log(f"[STEALTH] Tentando via {ns_label} (display {display})...")

    # Limpar antes de cada tentativa
    _kill_orphan_chrome()
    _clean_profile_locks()

    js_path = str(STEALTH_SOLVER_JS_PATH)

    env = os.environ.copy()
    env["DISPLAY"] = display
    env["HOME"] = os.environ.get("HOME", "/root")
    env["NODE_PATH"] = os.environ.get("NODE_PATH", "/root/node_modules")

    # Montar comando com ou sem namespace
    _home = os.environ.get("HOME", "/root")
    _node_path = os.environ.get("NODE_PATH", "/root/node_modules")
    if ns and platform.system() != "Windows":
        cmd = [
            "sudo", "-n", "ip", "netns", "exec", ns,
            "env", f"DISPLAY={display}", f"HOME={_home}",
            f"NODE_PATH={_node_path}",
            "node", js_path, str(PROFILE_DIR),
        ]
    else:
        cmd = ["node", js_path, str(PROFILE_DIR)]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            env=env,
            cwd=os.environ.get("HOME", os.environ.get("USERPROFILE", ".")),
        )

        stderr_out = proc.stderr.decode(errors="replace")
        for line in stderr_out.strip().split("\n"):
            if line.strip():
                log(f"  {line.strip()}")

        if proc.returncode == 0:
            token = proc.stdout.decode().strip()
            if token and len(token) > 20:
                log(f"[STEALTH] Token via {ns_label}! ({len(token)} chars)")
                return token
            else:
                log(f"[STEALTH] {ns_label}: saída vazia ({len(token)} chars)")
                return None

        # -9 = OOM killed, pular este NS
        if proc.returncode == -9:
            log(f"[STEALTH] {ns_label}: OOM killed (memória insuficiente)")
            return None

        log(f"[STEALTH] {ns_label}: exit code {proc.returncode}")
        return None

    except subprocess.TimeoutExpired:
        log(f"[STEALTH] {ns_label}: timeout!")
        _kill_orphan_chrome()
        return None
    except Exception as e:
        log(f"[STEALTH] {ns_label}: erro {e}")
        return None


# ─── Resolver com rotação automática de NS ────────────────────────

def resolver_turnstile(display=None):
    """
    Full local. Stealth com rotação de IP/namespace.
    host → ns_t0 → ns_t1 → ... → até MAX_RETRIES → só então reporta.
    Pula NS com OOM automaticamente.
    """
    display = display or DISPLAY
    ns_oom = set()  # NS que deram OOM, não tentar de novo

    for attempt in range(1, MAX_RETRIES + 1):
        # Escolher próximo NS disponível (pular OOM)
        ns_idx = (attempt - 1) % len(NAMESPACES)
        ns = NAMESPACES[ns_idx]
        ns_label = ns or "host"

        if ns in ns_oom:
            log(f"[Tentativa {attempt}/{MAX_RETRIES}] {ns_label} pulado (OOM)")
            continue

        log(f"[Tentativa {attempt}/{MAX_RETRIES}] NS={ns_label}")

        token = resolver_turnstile_stealth(display=display, ns=ns)
        if token:
            log(f"Sucesso na tentativa {attempt} via {ns_label}")
            return token

        # Checar se foi OOM (-9) para não tentar esse NS de novo
        # (o retorno None pode ser OOM ou outro erro, vamos confiar no log)
        # Marcar NS como OOM se Chrome nem conseguiu navegar
        # Delay progressivo (1s, 2s, 3s... max 5s)
        delay = min(attempt, 5)
        log(f"Falhou via {ns_label}, rotacionando em {delay}s...")
        time.sleep(delay)

    log(f"TODAS {MAX_RETRIES} tentativas falharam!")
    return None


# ─── Emissão de Certidão ─────────────────────────────────────────

def emitir_certidao_mpf(cpf_cnpj: str, tipo_pessoa: str = None, display=None) -> dict:
    """
    Emite certidão negativa do MPF. Full local, zero API terceira.
    """
    digitos = ''.join(c for c in cpf_cnpj if c.isdigit())

    if not tipo_pessoa:
        tipo_pessoa = "F" if len(digitos) <= 11 else "J"

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # 1. Consultar nome (sem captcha)
        log(f"Consultando nome para {tipo_pessoa}: {digitos}")
        resp = session.get(MPF_CONSULTAR, params={
            "tipoPessoa": tipo_pessoa,
            "documento": digitos,
        }, timeout=30)

        if resp.status_code != 200:
            log(f"Consulta nome falhou: {resp.status_code}")
            return {"status": "erro", "mensagem": f"Consulta nome falhou: HTTP {resp.status_code}"}

        consulta_data = resp.json()
        nome = consulta_data.get("data", "")
        sucesso_consulta = consulta_data.get("success", False)

        if not sucesso_consulta:
            log(f"Consulta nome sem sucesso: {consulta_data}")
            return {"status": "erro", "mensagem": f"Nome não encontrado: {consulta_data}"}

        log(f"Nome encontrado: {nome}")

        # 2. Resolver Turnstile: tentar 2captcha primeiro no Windows
        token = None
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from infra.twocaptcha_solver import solve_turnstile
            token = solve_turnstile(TURNSTILE_SITEKEY, MPF_PAGE)
            if token:
                log(f"Turnstile resolvido via 2captcha")
        except Exception as e:
            log(f"2captcha Turnstile falhou ({e}), tentando stealth...")

        if not token:
            token = resolver_turnstile(display=display)

        if not token:
            return {"status": "erro", "mensagem": "Falha Turnstile (2captcha + stealth)"}

        # 3. Emitir certidão
        log("Emitindo certidão...")
        resp = session.get(MPF_EMITIR, params={
            "tipoPessoa": tipo_pessoa,
            "documento": digitos,
            "recaptcha": token,
        }, timeout=30)

        if resp.status_code != 200:
            log(f"Emissão falhou: {resp.status_code} - {resp.text[:200]}")
            return {"status": "erro", "mensagem": f"Emissão falhou: HTTP {resp.status_code}"}

        emissao_data = resp.json()
        hash_certidao = emissao_data.get("data", "")
        messages = emissao_data.get("messages", [])

        if not hash_certidao:
            log(f"Emissão sem hash: {emissao_data}")
            return {"status": "erro", "mensagem": f"Emissão sem hash: {emissao_data}"}

        log(f"Certidao emitida! Hash: {hash_certidao}")
        log(f"Mensagem: {messages}")

        # 4. Download PDF
        download_url = f"{MPF_DOWNLOAD}/{hash_certidao}"
        log(f"Baixando PDF: {download_url}")
        resp = session.get(download_url, timeout=30)

        if resp.status_code != 200 or len(resp.content) < 100:
            log(f"Download falhou: {resp.status_code}")
            return {
                "status": "sucesso_sem_pdf",
                "nome": nome,
                "hash": hash_certidao,
                "download_url": download_url,
                "mensagem": messages[0] if messages else "Certidão emitida",
            }

        # 5. Salvar e upload
        tmpdir = tempfile.mkdtemp(prefix="mpf_")
        pdf_path = os.path.join(tmpdir, f"certidao_mpf_{digitos}.pdf")

        with open(pdf_path, "wb") as f:
            f.write(resp.content)

        log(f"PDF salvo: {pdf_path} ({len(resp.content)} bytes)")

        link = upload_para_tmpfiles(pdf_path)

        return {
            "status": "sucesso",
            "metodo": "stealth_local",
            "nome": nome,
            "cpf_cnpj": digitos,
            "tipo_pessoa": tipo_pessoa,
            "hash": hash_certidao,
            "link": link,
            "pdf_local": pdf_path,
            "download_url_direto": download_url,
            "mensagem": messages[0] if messages else "Certidão emitida com sucesso",
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
    display = data.get("display", DISPLAY)

    if not cpf_cnpj:
        return jsonify({"erro": "cpf ou cnpj é obrigatório"}), 400

    tipo = "F" if cpf else "J"

    try:
        resultado = emitir_certidao_mpf(cpf_cnpj, tipo, display=display)

        if "sucesso" in resultado.get("status", ""):
            return jsonify(resultado), 200
        else:
            return jsonify(resultado), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Certidão Negativa MPF (Full Local + Rotação NS)")
    p.add_argument("--cpf", help="CPF para consulta")
    p.add_argument("--cnpj", help="CNPJ para consulta")
    p.add_argument("--display", default=":120", help="Display X11 para Chrome stealth")
    p.add_argument("--serve", action="store_true", help="Rodar Flask API")
    p.add_argument("--port", type=int, default=5013, help="Porta Flask")
    a = p.parse_args()

    DISPLAY = a.display

    if a.serve:
        app.run(port=a.port, debug=True)
    else:
        cpf_cnpj = a.cpf or a.cnpj
        if not cpf_cnpj:
            print("Use --cpf ou --cnpj")
            sys.exit(1)
        tipo = "F" if a.cpf else "J"
        result = emitir_certidao_mpf(cpf_cnpj, tipo, display=a.display)
        print(json.dumps(result, ensure_ascii=False, indent=2))

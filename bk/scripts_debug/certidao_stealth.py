#!/usr/bin/env python3
"""
Certidão Stealth — Emite certidões usando Puppeteer-stealth token farm
======================================================================

Mesma técnica do CadUnico v13:
  - Chrome stealth com Google profile logado = score alto
  - reCAPTCHA v2 auto-passa SEM challenge visual
  - hCaptcha / Turnstile resolvem automaticamente
  - VPN namespace + rotate automático
  - ZERO 2captcha, ZERO custo, ZERO API terceira

Sites suportados: tcu, ibama, cpf_receita, mpf

Uso:
  python3 certidao_stealth.py --site tcu --cpf 12345678900
  python3 certidao_stealth.py --site ibama --cnpj 00000000000191
  python3 certidao_stealth.py --site cpf_receita --cpf 12345678900 --nascimento 01/01/1990
  python3 certidao_stealth.py --site mpf --cpf 12345678900
  python3 certidao_stealth.py --serve --port 5050  # API unificada
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import tempfile
import shutil
import requests
from pathlib import Path
from flask import Flask, request as flask_request, jsonify

app = Flask(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────
TOKEN_FARM = Path(__file__).parent / "infra" / "token_farm_certidao.js"
SOURCE_PROFILE = Path("/home/ramza/credenciais_cadunico/google_profile_logged")
PROFILE_BASE = Path(__file__).parent / "infra" / "profiles"
DISPLAY = os.environ.get("DISPLAY", ":120")

# Se estiver em namespace, usar ip netns exec
USE_NAMESPACE = os.environ.get("CERTIDAO_NS", "")  # ex: ns_t0


def log(msg):
    print(f"[CERT][{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


class CertidaoFarm:
    """Gerencia um token_farm_certidao.js para um site específico."""

    def __init__(self, site: str, display: str = ":120", ns: str = ""):
        self.site = site
        self.display = display
        self.ns = ns
        self.profile = PROFILE_BASE / site
        self.proc = None

    async def start(self):
        """Inicia o token_farm.js."""
        PROFILE_BASE.mkdir(parents=True, exist_ok=True)

        cmd = []
        if self.ns:
            cmd = ["sudo", "-n", "ip", "netns", "exec", self.ns,
                   "sudo", "-u", "ramza"]

        cmd += [
            "env", f"DISPLAY={self.display}", "HOME=/home/ramza",
            "NODE_TLS_REJECT_UNAUTHORIZED=0",
            "node", str(TOKEN_FARM),
            "--site", self.site,
            "--profile", str(self.profile),
            "--source-profile", str(SOURCE_PROFILE),
        ]

        log(f"Starting farm: {' '.join(cmd[-6:])}")
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        # Esperar ready
        try:
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=60)
            d = json.loads(line.decode().strip())
            if d.get("ok"):
                log(f"Farm {self.site} ready!")
                return True
            else:
                log(f"Farm failed: {d}")
                return False
        except asyncio.TimeoutError:
            log("Farm start TIMEOUT")
            return False
        except Exception as e:
            log(f"Farm start error: {e}")
            return False

    async def stop(self):
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.stdin.write(b'{"cmd":"quit"}\n')
                await self.proc.stdin.drain()
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except:
                try:
                    self.proc.kill()
                except:
                    pass
        self.proc = None

    async def _send(self, cmd: dict, timeout=60) -> dict:
        if not self.proc or self.proc.returncode is not None:
            return {"ok": False, "error": "proc_dead"}
        try:
            self.proc.stdin.write((json.dumps(cmd) + "\n").encode())
            await self.proc.stdin.drain()
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=timeout)
            if not line:
                return {"ok": False, "error": "empty"}
            return json.loads(line.decode().strip())
        except asyncio.TimeoutError:
            return {"ok": False, "error": "timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def gen_token(self) -> str:
        resp = await self._send({"cmd": "gen"}, timeout=60)
        if resp.get("ok") and resp.get("token"):
            log(f"Token OK ({len(resp['token'])} chars)")
            return resp["token"]
        log(f"Token FAIL: {resp.get('error', '?')}")
        return ""

    async def submit(self, data: dict) -> dict:
        resp = await self._send({"cmd": "submit", "data": data}, timeout=30)
        return resp

    async def reload(self):
        resp = await self._send({"cmd": "reload"}, timeout=30)
        return resp.get("ok", False)

    async def info(self) -> dict:
        return await self._send({"cmd": "info"}, timeout=10)


# ─── Emissão de Certidões ────────────────────────────────────────

async def emitir_tcu(farm: CertidaoFarm, cpf_cnpj: str) -> dict:
    """TCU: gerar token → preencher form → submeter."""
    digitos = ''.join(c for c in cpf_cnpj if c.isdigit())

    # 1. Gerar token reCAPTCHA
    token = await farm.gen_token()
    if not token:
        # Retry com reload
        await farm.reload()
        token = await farm.gen_token()
        if not token:
            return {"status": "erro", "mensagem": "Token reCAPTCHA não gerado"}

    # 2. Submeter formulário
    result = await farm.submit({
        "cpf": digitos if len(digitos) <= 11 else "",
        "cnpj": digitos if len(digitos) > 11 else "",
    })

    if not result.get("ok"):
        return {"status": "erro", "mensagem": result.get("error", "Submit falhou")}

    html = result.get("html", "")
    text = result.get("text", "")

    # 3. Analisar resultado
    if "CERTIFICA" in html or "NÃO CONSTA" in html or "N&Atilde;O CONSTA" in html:
        tipo = "nada_consta"
    elif "CONSTA" in html.upper() and "NÃO" not in html.upper():
        tipo = "consta"
    else:
        tipo = "verificar"

    # Salvar e upload
    link = salvar_e_upload(html, f"tcu_{digitos}")

    return {
        "status": "sucesso",
        "tipo_certidao": tipo,
        "cpf_cnpj": digitos,
        "link": link,
        "resultado": text[:500],
    }


async def emitir_ibama(farm: CertidaoFarm, cpf_cnpj: str) -> dict:
    """IBAMA: gerar token → preencher CPF → pesquisar."""
    digitos = ''.join(c for c in cpf_cnpj if c.isdigit())

    token = await farm.gen_token()
    if not token:
        await farm.reload()
        token = await farm.gen_token()
        if not token:
            return {"status": "erro", "mensagem": "Token reCAPTCHA não gerado"}

    result = await farm.submit({"cpf": digitos})

    if not result.get("ok"):
        return {"status": "erro", "mensagem": result.get("error", "Submit falhou")}

    html = result.get("html", "")
    text = result.get("text", "")
    link = salvar_e_upload(html, f"ibama_{digitos}")

    return {
        "status": "sucesso",
        "cpf_cnpj": digitos,
        "link": link,
        "resultado": text[:500],
    }


async def emitir_cpf_receita(farm: CertidaoFarm, cpf: str, data_nascimento: str) -> dict:
    """CPF Receita: gerar token hCaptcha → preencher CPF+DN → consultar."""
    digitos = ''.join(c for c in cpf if c.isdigit())

    token = await farm.gen_token()
    if not token:
        await farm.reload()
        token = await farm.gen_token()
        if not token:
            return {"status": "erro", "mensagem": "Token hCaptcha não gerado"}

    result = await farm.submit({
        "cpf": digitos,
        "data_nascimento": data_nascimento,
    })

    if not result.get("ok"):
        return {"status": "erro", "mensagem": result.get("error", "Submit falhou")}

    html = result.get("html", "")
    text = result.get("text", "")

    # Extrair situação
    import re
    m = re.search(r'Situa[çc][aã]o\s*Cadastral[:\s]*</span>\s*<[^>]*>([^<]+)', html, re.IGNORECASE)
    situacao = m.group(1).strip() if m else ""
    m = re.search(r'Nome[:\s]*</span>\s*<[^>]*>([^<]+)', html, re.IGNORECASE)
    nome = m.group(1).strip() if m else ""

    link = salvar_e_upload(html, f"cpf_{digitos}")

    return {
        "status": "sucesso" if situacao or nome else "verificar",
        "cpf": digitos,
        "nome": nome,
        "situacao_cadastral": situacao,
        "link": link,
        "resultado": text[:500],
    }


async def emitir_mpf(farm: CertidaoFarm, cpf_cnpj: str) -> dict:
    """MPF: Turnstile resolve auto → consultar nome → emitir."""
    digitos = ''.join(c for c in cpf_cnpj if c.isdigit())
    tipo_pessoa = "F" if len(digitos) <= 11 else "J"

    # Turnstile deve resolver sozinho no browser
    token = await farm.gen_token()
    if not token:
        await farm.reload()
        await asyncio.sleep(5)  # Turnstile precisa de mais tempo
        token = await farm.gen_token()
        if not token:
            # Tentar API direta com requests (sem captcha — talvez a consulta funcione)
            return await emitir_mpf_api(digitos, tipo_pessoa, token="")

    # Usar API REST direta com o token Turnstile
    return await emitir_mpf_api(digitos, tipo_pessoa, token)


async def emitir_mpf_api(documento: str, tipo_pessoa: str, token: str) -> dict:
    """MPF via API REST (mais confiável que browser form)."""
    MPF_BASE = "https://aplicativos.mpf.mp.br"

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/144.0.0.0",
        "Accept": "application/json",
        "Referer": f"{MPF_BASE}/ouvidoria/app/cidadao/certidao",
    })

    try:
        # Consultar nome
        resp = session.get(f"{MPF_BASE}/ouvidoria/rest/v1/publico/certidao/consultar",
                           params={"tipoPessoa": tipo_pessoa, "documento": documento}, timeout=15)
        if resp.status_code != 200:
            return {"status": "erro", "mensagem": f"Consulta falhou: {resp.status_code}"}

        nome = resp.json().get("data", "")
        if not nome:
            return {"status": "erro", "mensagem": "Nome não encontrado"}

        if not token:
            return {"status": "parcial", "nome": nome, "mensagem": "Token Turnstile não disponível"}

        # Emitir
        resp = session.get(f"{MPF_BASE}/ouvidoria/rest/v1/publico/certidao/emitir",
                           params={"tipoPessoa": tipo_pessoa, "documento": documento, "recaptcha": token},
                           timeout=15)
        if resp.status_code != 200:
            return {"status": "erro", "mensagem": f"Emissão falhou: {resp.status_code}"}

        hash_cert = resp.json().get("data", "")
        if not hash_cert:
            return {"status": "erro", "mensagem": "Sem hash na resposta"}

        # Download PDF
        download_url = f"{MPF_BASE}/ouvidoria/rest/v1/publico/certidao/download/{hash_cert}"
        resp = session.get(download_url, timeout=15)

        tmpdir = tempfile.mkdtemp(prefix="mpf_")
        pdf_path = os.path.join(tmpdir, f"certidao_mpf_{documento}.pdf")
        with open(pdf_path, "wb") as f:
            f.write(resp.content)

        link = upload_para_tmpfiles(pdf_path)

        return {
            "status": "sucesso",
            "nome": nome,
            "hash": hash_cert,
            "link": link,
            "download_url": download_url,
        }

    except Exception as e:
        return {"status": "erro", "mensagem": str(e)}


# ─── Helpers ─────────────────────────────────────────────────────

def salvar_e_upload(html: str, prefix: str) -> str:
    tmpdir = tempfile.mkdtemp(prefix=f"{prefix}_")
    html_path = os.path.join(tmpdir, f"{prefix}.html")
    pdf_path = os.path.join(tmpdir, f"{prefix}.pdf")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Tentar gerar PDF
    link = None
    try:
        os.system(f'wkhtmltopdf --quiet "{html_path}" "{pdf_path}" 2>/dev/null')
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 100:
            link = upload_para_tmpfiles(pdf_path)
    except:
        pass

    if not link:
        link = upload_para_tmpfiles(html_path)

    return link


def upload_para_tmpfiles(caminho_arquivo):
    try:
        with open(caminho_arquivo, 'rb') as f:
            response = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
        if response.status_code == 200:
            link = response.json().get("data", {}).get("url")
            log(f"Upload OK: {link}")
            return link
    except Exception as e:
        log(f"Upload erro: {e}")
    return None


# ─── Main Entry Points ──────────────────────────────────────────

EMITTERS = {
    "tcu": emitir_tcu,
    "ibama": emitir_ibama,
    "cpf_receita": emitir_cpf_receita,
    "mpf": emitir_mpf,
}


async def emitir_certidao(site: str, **kwargs) -> dict:
    """Abre farm, emite certidão, fecha farm."""
    display = kwargs.pop("display", DISPLAY)
    ns = kwargs.pop("ns", USE_NAMESPACE)

    farm = CertidaoFarm(site, display=display, ns=ns)
    try:
        ok = await farm.start()
        if not ok:
            return {"status": "erro", "mensagem": "Farm não iniciou"}

        emitter = EMITTERS.get(site)
        if not emitter:
            return {"status": "erro", "mensagem": f"Site desconhecido: {site}"}

        result = await emitter(farm, **kwargs)
        return result

    finally:
        await farm.stop()


def emitir_sync(site: str, **kwargs) -> dict:
    """Wrapper síncrono."""
    return asyncio.run(emitir_certidao(site, **kwargs))


# ─── Flask API ──────────────────────────────────────────────────

@app.route("/certidao/<site>", methods=["POST"])
def api_certidao(site):
    data = flask_request.json or {}
    cpf = data.get("cpf", "")
    cnpj = data.get("cnpj", "")
    cpf_cnpj = cpf or cnpj
    nascimento = data.get("data_nascimento", "") or data.get("nascimento", "")

    if not cpf_cnpj and site != "mpf":
        return jsonify({"erro": "cpf ou cnpj obrigatório"}), 400

    try:
        if site == "cpf_receita":
            if not nascimento:
                return jsonify({"erro": "data_nascimento obrigatório"}), 400
            result = emitir_sync(site, cpf=cpf_cnpj, data_nascimento=nascimento)
        elif site == "mpf":
            result = emitir_sync(site, cpf_cnpj=cpf_cnpj)
        else:
            result = emitir_sync(site, cpf_cnpj=cpf_cnpj)

        status_code = 200 if "sucesso" in result.get("status", "") else 500
        return jsonify(result), status_code

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


# ─── CLI ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Certidão Stealth — Token Farm")
    p.add_argument("--site", required=False, choices=list(SITES.keys()) if 'SITES' in dir() else ["tcu","ibama","cpf_receita","mpf"])
    p.add_argument("--cpf", help="CPF")
    p.add_argument("--cnpj", help="CNPJ")
    p.add_argument("--nascimento", help="Data nascimento (dd/mm/aaaa)")
    p.add_argument("--display", default=":120")
    p.add_argument("--ns", default="", help="Namespace VPN (ex: ns_t0)")
    p.add_argument("--serve", action="store_true", help="API Flask unificada")
    p.add_argument("--port", type=int, default=5050)
    a = p.parse_args()

    DISPLAY = a.display
    USE_NAMESPACE = a.ns

    if a.serve:
        log("API unificada em todas as portas:")
        log("  POST /certidao/tcu         {cpf/cnpj}")
        log("  POST /certidao/ibama       {cpf/cnpj}")
        log("  POST /certidao/cpf_receita {cpf, data_nascimento}")
        log("  POST /certidao/mpf         {cpf/cnpj}")
        app.run(port=a.port, debug=False)
    else:
        if not a.site:
            print("Use --site (tcu|ibama|cpf_receita|mpf)")
            sys.exit(1)

        cpf_cnpj = a.cpf or a.cnpj
        if not cpf_cnpj:
            print("Use --cpf ou --cnpj")
            sys.exit(1)

        kwargs = {}
        if a.site == "cpf_receita":
            if not a.nascimento:
                print("CPF Receita requer --nascimento")
                sys.exit(1)
            kwargs = {"cpf": cpf_cnpj, "data_nascimento": a.nascimento}
        else:
            kwargs = {"cpf_cnpj": cpf_cnpj}

        result = emitir_sync(a.site, **kwargs)
        print(json.dumps(result, ensure_ascii=False, indent=2))

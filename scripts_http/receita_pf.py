"""Receita Federal PF — Puppeteer stealth + 2captcha hCaptcha (sem Selenium)"""
import json
import os
import sys
import subprocess
import tempfile
import requests
from pathlib import Path

SOLVER_JS = Path(__file__).parent.parent / "infra" / "receita_pf_solver.js"
CAPTCHA_KEY = os.environ.get("CAPTCHA_API_KEY", "")
NODE_PATH = os.environ.get("NODE_PATH", str(Path(__file__).parent.parent / "node_modules"))


def upload_pdf(pdf_path: str) -> str:
    try:
        with open(pdf_path, "rb") as f:
            r = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": f}, timeout=30)
        if r.status_code == 200:
            return r.json().get("data", {}).get("url", "")
    except Exception:
        pass
    return None


def emitir_certidao_receita_pf(cpf: str, dt_nascimento: str) -> dict:
    """Emite certidao PF via Puppeteer stealth + 2captcha."""
    print(f"[Receita PF] Puppeteer para CPF: {cpf}")
    tmpdir = tempfile.mkdtemp()

    env = os.environ.copy()
    env["NODE_PATH"] = NODE_PATH
    if CAPTCHA_KEY:
        env["CAPTCHA_API_KEY"] = CAPTCHA_KEY

    cmd = ["node", str(SOLVER_JS), cpf, dt_nascimento, tmpdir, CAPTCHA_KEY]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                                cwd=os.environ.get("HOME", os.environ.get("USERPROFILE", ".")), env=env)

        if result.stderr:
            for line in result.stderr.strip().split("\n")[-10:]:
                print(f"  {line}")

        stdout = result.stdout.strip()
        if not stdout:
            return {"status": "erro", "mensagem": "Solver sem output"}

        data = json.loads(stdout.strip().split("\n")[-1])
        status = data.get("status", "erro")
        pdf_path = data.get("pdf_path")

        if status == "sucesso" and pdf_path and os.path.exists(pdf_path):
            size = os.path.getsize(pdf_path)
            print(f"[Receita PF] PDF: {size} bytes")
            if size < 1000:
                return {"status": "falha", "mensagem": "PDF muito pequeno"}
            link = upload_pdf(pdf_path)
            return {"status": "sucesso", "link": link, "tipo_certidao": data.get("tipo_certidao", "receita_pf"),
                    "mensagem": data.get("message", "Certidao emitida")}

        return {"status": status, "mensagem": data.get("message", "Falha")}

    except subprocess.TimeoutExpired:
        return {"status": "erro", "mensagem": "Timeout (180s)"}
    except json.JSONDecodeError as e:
        return {"status": "erro", "mensagem": f"JSON invalido: {str(e)[:100]}"}
    except Exception as e:
        return {"status": "erro", "mensagem": str(e)[:200]}

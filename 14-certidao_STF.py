#!/usr/bin/env python3
"""
14 - Certidão STF (Supremo Tribunal Federal)
AWS WAF Captcha + reCAPTCHA Enterprise — tudo resolvido localmente
Stealth Chrome bypassa WAF, executa reCAPTCHA Enterprise, POST na API, baixa PDF

Fluxo:
  1. Puppeteer-stealth abre STF
  2. Audio challenge do WAF → Whisper medium (GPU)
  3. grecaptcha.enterprise.execute() → token reCAPTCHA
  4. POST /api/certidao/distribuicao com X-TOKEN-CAPTCHA
  5. Se certidão online → download PDF do emissor
  6. Upload para tmpfiles.org

Tipos de certidão disponíveis:
  - distribuicao (padrão — nada consta de processos)
  - antecedentes-criminais
  - fins-eleitorais
  - atuacao-de-advogado
  - objeto-e-pe (requer classe + número do processo)
"""
import json
import os
import sys
import time
import subprocess
import tempfile
from pathlib import Path
import requests
from flask import Flask, request as flask_request, jsonify

app = Flask(__name__)

# ─── CONFIG ───────────────────────────────────────────────────────
SOLVER_JS = Path(__file__).parent / "infra" / "stf_certidao_solver.js"
DISPLAY = os.environ.get("CAPTCHA_DISPLAY", ":121")
MAX_RETRIES = 6
NAMESPACES = ["", "ns_t0", "ns_t1", "ns_t2", "ns_t3", "ns_t4"]


def log(msg):
    print(f"[STF][{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def whisper_transcribe(audio_path: str) -> str:
    """Transcreve audio AWS WAF com Whisper medium (GPU)."""
    log(f"Whisper transcrevendo: {audio_path}")

    # Convert AAC to WAV
    wav_path = audio_path.rsplit(".", 1)[0] + ".wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", wav_path],
            capture_output=True, timeout=10,
        )
        if os.path.exists(wav_path):
            audio_path = wav_path
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["python3", "-c", f"""
import whisper, re, sys

model = whisper.load_model("medium", device="cuda")
result = model.transcribe("{audio_path}", language="en", fp16=True)
text = result["text"].strip()
segments = result.get("segments", [])
print("RAW: " + text, file=sys.stderr)
print("SEGMENTS: " + str(len(segments)), file=sys.stderr)
for s in segments:
    print(f"  SEG [{{s['start']:.1f}}-{{s['end']:.1f}}]: {{s['text'].strip()}}", file=sys.stderr)

lower = text.lower()
noise = {{"the","a","an","is","are","was","were","of","and","to","in","for","from","which","that","this",
         "not","but","its","with","has","been","will","can","may","must","also","by","me","or","on",
         "every","had","ever","make","more","easy","for","others","whether","we","know","no","little",
         "thing","cannot","properly","call","that","is","whole","plan","are","from"}}

def extract_target_words(text, segments):
    '''AWS WAF audio: "Type one of the two following words spoken by me. Word1. Word2."
    Mixed with philosophical noise. Target words are SHORT standalone segments.'''
    lo = text.lower()
    
    # BEST METHOD: Use segments — find short standalone segments (1-2 words)
    # Target words are always single-word segments that stand out from noise
    if segments and len(segments) >= 2:
        short_segs = []
        instruction_noise = {{"type","one","two","the","following","words","spoken","by","me","to","philosophers","of"}}
        for seg in segments:
            st = seg["text"].strip().rstrip(".").lower()
            words_in_seg = re.findall(r'[a-z]+', st)
            # Short segment (1-2 words) = likely a target word
            if len(words_in_seg) <= 2:
                clean_words = [w for w in words_in_seg if w not in instruction_noise and w not in noise and len(w) > 2]
                if clean_words:
                    short_segs.append(clean_words[0])
        if short_segs:
            print(f"SHORT_SEGS: {{short_segs}}", file=sys.stderr)
            return short_segs[0]
    
    # FALLBACK 1: Pattern after "by me" — works when no noise overlap
    if "by me" in lo:
        after = lo.split("by me")[-1].strip()
        sentences = [s.strip() for s in after.split(".") if s.strip()]
        for sent in sentences[:3]:
            words = [w for w in re.findall(r'[a-z]+', sent) if w not in noise and len(w) > 2]
            # Only use if the sentence is short (real target, not noise)
            if words and len(sent.split()) <= 4:
                return words[0]
    
    # FALLBACK 2: Last segment is often the last target word
    if segments:
        last = segments[-1]["text"].strip().rstrip(".").lower()
        lw = re.findall(r'[a-z]+', last)
        lw = [w for w in lw if w not in noise and len(w) > 2]
        if lw and len(last.split()) <= 3:
            return lw[0]
    
    return None

answer = extract_target_words(text, segments)

if not answer:
    # Last resort — uncommon words in full text
    all_words = re.findall(r'[a-z]+', lower)
    common = noise | {{"type","one","two","following","words","spoken","way","much","other","such","these",
                       "those","what","when","where","how","why","who","they","them","their","would","could",
                       "should","only","just","into","very","some","even","most","here","there","then","than",
                       "david","hume","nature","world","introduction","necessary","philosophers","nearest",
                       "shown","came","time","seems"}}
    candidates = [w for w in all_words if w not in common and len(w) > 3]
    if candidates:
        answer = candidates[0]

if not answer:
    clean = re.sub(r'[^a-z0-9 ]', '', lower).strip()
    answer = clean.split()[-1] if clean else "unknown"

print(answer)
"""],
            capture_output=True, timeout=45, cwd=os.environ.get("HOME", "/root"),
        )
        text = result.stdout.decode().strip()
        stderr_out = result.stderr.decode()
        for line in stderr_out.strip().split("\n"):
            if line.strip():
                log(f"  Whisper: {line.strip()}")
        if text:
            log(f"Whisper resultado: '{text}'")
            return text
        return ""
    except Exception as e:
        log(f"Whisper erro: {e}")
        return ""


def run_stf_solver(cpf_cnpj: str, tipo: str = "distribuicao", nome: str = "",
                   extra: dict = None, display: str = ":121", ns: str = "") -> dict:
    """
    Executa o solver JS com protocolo stdin/stdout para Whisper.
    Retorna dict com resultado da certidão.
    """
    ns_label = ns or "host"
    digitos = ''.join(c for c in cpf_cnpj if c.isdigit())
    extra_json = json.dumps(extra or {})

    env = os.environ.copy()
    env["DISPLAY"] = display
    env["HOME"] = os.environ.get("HOME", "/root")
    env["NODE_PATH"] = os.environ.get("NODE_PATH", "/root/node_modules")

    _home = os.environ.get("HOME", "/root")
    _node_path = os.environ.get("NODE_PATH", "/root/node_modules")
    if ns:
        cmd = [
            "sudo", "-n", "ip", "netns", "exec", ns,
            "env", f"DISPLAY={display}", f"HOME={_home}",
            f"NODE_PATH={_node_path}",
            "node", str(SOLVER_JS), digitos, tipo, nome, extra_json,
        ]
    else:
        cmd = ["node", str(SOLVER_JS), digitos, tipo, nome, extra_json]

    log(f"[{ns_label}] Executando solver para {digitos} (tipo={tipo})")

    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, cwd=os.environ.get("HOME", "/root"),
        )

        result = {"status": "erro", "mensagem": "Timeout"}
        start = time.time()
        timeout = 90

        while time.time() - start < timeout:
            try:
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                    continue

                msg = json.loads(line.decode().strip())
                status = msg.get("status", "")

                if status == "audio_challenge":
                    audio_file = msg.get("audio_file", "")
                    answer = whisper_transcribe(audio_file)
                    if answer:
                        response = json.dumps({"answer": answer}) + "\n"
                        proc.stdin.write(response.encode())
                        proc.stdin.flush()
                    else:
                        proc.stdin.write(b'{"answer":""}\n')
                        proc.stdin.flush()

                elif status == "waf_solved":
                    log(f"[{ns_label}] WAF resolvido!")

                elif status == "certidao_result":
                    data = msg.get("data", {})
                    pdf_path = msg.get("pdf_path")
                    protocolo = msg.get("protocolo")

                    result = {
                        "status": "sucesso",
                        "cpf_cnpj": digitos,
                        "tipo_certidao": tipo,
                        "metodo": "local_audio_whisper",
                    }

                    # Extrair info da resposta da API
                    if isinstance(data, dict):
                        result["gerada_online"] = data.get("geradaOnline", False)
                        result["nome"] = data.get("sujeitoDaCertidao", nome)
                        if protocolo:
                            result["protocolo"] = protocolo
                        # Copiar campos relevantes
                        for k in ["mensagem", "tipoCertidao", "situacao"]:
                            if k in data:
                                result[k] = data[k]

                    # Upload PDF
                    if pdf_path and os.path.exists(pdf_path):
                        result["pdf_size"] = os.path.getsize(pdf_path)
                        link = upload_para_tmpfiles(pdf_path)
                        result["link"] = link
                    elif protocolo:
                        result["mensagem"] = f"Certidão em processamento. Protocolo: {protocolo}"

                    break

                elif status == "api_error":
                    data = msg.get("data", {})
                    err_msg = ""
                    if isinstance(data, dict):
                        err_msg = data.get("mensagem") or data.get("text", "") or data.get("error", "")
                        if isinstance(err_msg, dict):
                            err_msg = json.dumps(err_msg)
                    result = {
                        "status": "erro",
                        "mensagem": err_msg or "Erro na API do STF",
                        "cpf_cnpj": digitos,
                        "api_response": data,
                    }
                    break

                elif status == "error":
                    result = {
                        "status": "erro",
                        "mensagem": msg.get("error", "Erro desconhecido"),
                        "cpf_cnpj": digitos,
                    }
                    break

            except json.JSONDecodeError:
                continue
            except Exception as e:
                log(f"[{ns_label}] Erro leitura: {e}")
                break

        try:
            proc.kill()
        except Exception:
            pass

        # Log stderr (últimas linhas)
        try:
            stderr = proc.stderr.read().decode(errors="replace")
            for line in stderr.strip().split("\n")[-10:]:
                if line.strip():
                    log(f"  {line.strip()}")
        except Exception:
            pass

        return result

    except Exception as e:
        log(f"[{ns_label}] Erro geral: {e}")
        return {"status": "erro", "mensagem": str(e)}


def emitir_certidao_stf(cpf_cnpj: str, tipo: str = "distribuicao",
                        nome: str = "", extra: dict = None) -> dict:
    """
    Emite certidão do STF com rotação de namespace em caso de falha.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        ns_idx = (attempt - 1) % len(NAMESPACES)
        ns = NAMESPACES[ns_idx]
        ns_label = ns or "host"

        log(f"[Tentativa {attempt}/{MAX_RETRIES}] NS={ns_label}")

        result = run_stf_solver(
            cpf_cnpj=cpf_cnpj, tipo=tipo, nome=nome,
            extra=extra, display=DISPLAY, ns=ns,
        )

        if result.get("status") == "sucesso":
            log(f"Sucesso na tentativa {attempt} via {ns_label}")
            return result

        # Se erro de API (não de WAF), não precisa rotacionar
        if result.get("api_response"):
            log(f"Erro de API (não de WAF): {result.get('mensagem', '')}")
            return result

        delay = min(attempt, 3)
        log(f"Falhou via {ns_label}: {result.get('mensagem', '')}")
        log(f"Rotacionando em {delay}s...")
        time.sleep(delay)

    log(f"TODAS {MAX_RETRIES} tentativas falharam!")
    return result


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
    tipo = data.get("tipo", "distribuicao")
    nome = data.get("nome", "")
    extra = {k: v for k, v in data.items()
             if k not in ("cpf", "cnpj", "tipo", "nome")}

    if not cpf_cnpj:
        return jsonify({"erro": "cpf ou cnpj é obrigatório"}), 400

    try:
        resultado = emitir_certidao_stf(cpf_cnpj, tipo=tipo, nome=nome, extra=extra)
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
    p = argparse.ArgumentParser(description="Certidão STF (local solver — WAF + reCAPTCHA Enterprise)")
    p.add_argument("--cpf", help="CPF para consulta")
    p.add_argument("--cnpj", help="CNPJ para consulta")
    p.add_argument("--tipo", default="distribuicao",
                   choices=["distribuicao", "antecedentes-criminais", "fins-eleitorais",
                            "atuacao-de-advogado", "objeto-e-pe"],
                   help="Tipo de certidão")
    p.add_argument("--nome", default="", help="Nome do sujeito da certidão")
    p.add_argument("--display", default=":121", help="Display X11")
    p.add_argument("--serve", action="store_true", help="Rodar Flask API")
    p.add_argument("--port", type=int, default=5014, help="Porta Flask")
    a = p.parse_args()

    DISPLAY = a.display

    if a.serve:
        app.run(port=a.port, debug=True)
    else:
        cpf_cnpj = a.cpf or a.cnpj
        if not cpf_cnpj:
            print("Use --cpf ou --cnpj")
            sys.exit(1)
        result = emitir_certidao_stf(cpf_cnpj, tipo=a.tipo, nome=a.nome)
        print(json.dumps(result, ensure_ascii=False, indent=2))

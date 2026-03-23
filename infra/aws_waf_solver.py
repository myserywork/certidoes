#!/usr/bin/env python3
"""
AWS WAF Audio Solver — Local (Chrome stealth + Whisper GPU)
Resolve o AWS WAF captcha via audio challenge + Whisper.
Zero API externa.

Uso:
    from infra.aws_waf_solver import solve_aws_waf
    cookie = solve_aws_waf("https://certidoes.stf.jus.br/", display=":121")
"""
import json
import os
import subprocess
import sys
import time
import platform
from pathlib import Path

SOLVER_JS = Path(__file__).parent / "aws_waf_audio_solver.js"
MAX_RETRIES = 6
NAMESPACES = [""] if platform.system() == "Windows" else ["", "ns_t0", "ns_t1", "ns_t2", "ns_t3", "ns_t4"]


def log(msg):
    print(f"[AWSWAF][{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def whisper_transcribe(audio_path: str, language: str = "en") -> str:
    """Transcreve audio com Whisper local (GPU)."""
    log(f"Whisper transcrevendo: {audio_path}")
    # Convert AAC to WAV first if needed (Whisper works better with wav)
    wav_path = audio_path.rsplit(".", 1)[0] + ".wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", wav_path],
            capture_output=True, timeout=10,
        )
        if os.path.exists(wav_path):
            audio_path = wav_path
    except Exception:
        pass  # Use original if ffmpeg fails

    try:
        result = subprocess.run(
            [
                "python3", "-c",
                f"""
import whisper, re
model = whisper.load_model("medium", device="cuda")
result = model.transcribe("{audio_path}", language="{language}", fp16=True)
text = result["text"].strip()
import sys
print("RAW: " + text, file=sys.stderr)

# AWS WAF audio: "Type one of the two following words spoken by me. Word1. Word2."
# Strategy: use segments to find the target words (last 1-2 segments after instruction)
segments = result.get("segments", [])
lower = text.lower()

# Method 1: Pattern match on "by me"
if "by me" in lower:
    after = lower.split("by me")[-1].strip()
    # Split by periods/sentences to get clean words
    parts = [p.strip() for p in after.replace(".", " ").replace(",", " ").split() if p.strip()]
    noise = set(["the","a","an","is","are","was","were","of","and","to","in","for","from","which","that","this","not","but","its","with","has","been","will","can","may","must","also"])
    words = [w for w in parts if w.lower() not in noise and len(w) > 2 and w.isalpha()]
    if words:
        print(words[0].lower())
    else:
        # Fallback: last segment text
        if segments:
            last = segments[-1]["text"].strip().lower()
            clean = re.findall(r'[a-z]+', last)
            clean = [w for w in clean if w not in noise and len(w) > 2]
            print(clean[0] if clean else last)
        else:
            print(text.split()[-1].lower())
# Method 2: Use segments - last segment(s) usually contain the target words
elif segments and len(segments) >= 2:
    last_seg = segments[-1]["text"].strip().lower()
    words = re.findall(r'[a-z]+', last_seg)
    noise = set(["the","a","an","is","are","was","were","of","and","to","in"])
    words = [w for w in words if w not in noise and len(w) > 2]
    print(words[0] if words else last_seg)
else:
    clean = re.sub(r'[^a-z0-9 ]', '', lower).strip()
    print(clean.split()[-1] if clean else "unknown")
"""
            ],
            capture_output=True,
            timeout=30,
            cwd=os.environ.get("HOME", os.environ.get("USERPROFILE", ".")),
        )
        text = result.stdout.decode().strip()
        if text:
            log(f"Whisper resultado: '{text}'")
            return text
        else:
            log(f"Whisper vazio. stderr: {result.stderr.decode()[:200]}")
            return ""
    except subprocess.TimeoutExpired:
        log("Whisper timeout!")
        return ""
    except Exception as e:
        log(f"Whisper erro: {e}")
        return ""


def solve_aws_waf_single(url: str, display: str = ":121", ns: str = "", timeout: int = 60) -> str:
    """Uma tentativa de resolver AWS WAF. Retorna cookie string ou vazio."""
    ns_label = ns or "host"
    log(f"[{ns_label}] Abrindo {url}")

    env = os.environ.copy()
    env["DISPLAY"] = display
    env["HOME"] = os.environ.get("HOME", "/root")
    env["NODE_PATH"] = os.environ.get("NODE_PATH", "/root/node_modules")

    _home = os.environ.get("HOME", "/root")
    _node_path = os.environ.get("NODE_PATH", "/root/node_modules")
    if ns and platform.system() != "Windows":
        cmd = [
            "sudo", "-n", "ip", "netns", "exec", ns,
            "env", f"DISPLAY={display}", f"HOME={_home}",
            f"NODE_PATH={_node_path}",
            "node", str(SOLVER_JS), url,
        ]
    else:
        cmd = ["node", str(SOLVER_JS), url]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=os.environ.get("HOME", os.environ.get("USERPROFILE", ".")),
        )

        start = time.time()
        cookie = ""

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

                if status == "no_captcha":
                    log(f"[{ns_label}] Sem captcha WAF — acesso direto")
                    cookie = "NO_CAPTCHA"
                    break

                elif status == "solved":
                    cookie = msg.get("cookie", "")
                    log(f"[{ns_label}] Resolvido! Cookie: {cookie[:50]}...")
                    break

                elif status == "audio_challenge":
                    audio_file = msg.get("audio_file", "")
                    log(f"[{ns_label}] Audio challenge: {audio_file}")
                    answer = whisper_transcribe(audio_file)
                    if answer:
                        response = json.dumps({"answer": answer}) + "\n"
                        proc.stdin.write(response.encode())
                        proc.stdin.flush()
                        log(f"[{ns_label}] Resposta enviada: '{answer}'")
                    else:
                        log(f"[{ns_label}] Whisper falhou")
                        proc.stdin.write(b'{"answer":""}\n')
                        proc.stdin.flush()

                elif status in ("error", "failed"):
                    log(f"[{ns_label}] {status}: {msg.get('error', '?')}")
                    break

            except json.JSONDecodeError:
                continue
            except Exception as e:
                log(f"[{ns_label}] Read erro: {e}")
                break

        try:
            proc.kill()
        except Exception:
            pass

        # Log stderr
        try:
            stderr = proc.stderr.read().decode(errors="replace")
            for line in stderr.strip().split("\n"):
                if line.strip():
                    log(f"  {line.strip()}")
        except Exception:
            pass

        return cookie

    except Exception as e:
        log(f"[{ns_label}] Erro geral: {e}")
        return ""


def solve_aws_waf(url: str, display: str = ":121") -> str:
    """Resolve AWS WAF com rotação de namespace. Retorna cookie ou vazio."""
    for attempt in range(1, MAX_RETRIES + 1):
        ns_idx = (attempt - 1) % len(NAMESPACES)
        ns = NAMESPACES[ns_idx]
        ns_label = ns or "host"

        log(f"[Tentativa {attempt}/{MAX_RETRIES}] NS={ns_label}")

        cookie = solve_aws_waf_single(url=url, display=display, ns=ns)

        if cookie:
            log(f"Sucesso na tentativa {attempt} via {ns_label}")
            return cookie

        delay = min(attempt, 3)
        log(f"Falhou via {ns_label}, rotacionando em {delay}s...")
        time.sleep(delay)

    log(f"TODAS {MAX_RETRIES} tentativas falharam!")
    return ""


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="AWS WAF Audio Solver (local)")
    p.add_argument("url", help="URL com AWS WAF captcha")
    p.add_argument("--display", default=":121", help="Display X11")
    a = p.parse_args()

    cookie = solve_aws_waf(a.url, display=a.display)
    if cookie:
        print(f"COOKIE: {cookie[:80]}...")
    else:
        print("FALHOU")
        sys.exit(1)

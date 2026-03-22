#!/usr/bin/env python3
"""
Local CAPTCHA Solver — reCAPTCHA v2 via Audio + Whisper
Zero API externa. Tudo local: Chrome stealth + Whisper GPU.

Uso:
    from infra.local_captcha_solver import solve_recaptcha_v2
    token = solve_recaptcha_v2("https://site.com/pagina", display=":120")
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SOLVER_JS = Path(__file__).parent / "recaptcha_audio_solver.js"
PROFILE_BASE = Path(__file__).parent / "profiles"
SOURCE_PROFILE = Path("/tmp/chrome_profile")

# Namespaces para rotação
NAMESPACES = ["", "ns_t0", "ns_t1", "ns_t2", "ns_t3", "ns_t4"]
MAX_RETRIES = 10


def log(msg):
    print(f"[LCAP][{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def whisper_transcribe(audio_path: str, language: str = "en") -> str:
    """Transcreve audio com Whisper local (GPU)."""
    log(f"Whisper transcrevendo: {audio_path}")
    try:
        result = subprocess.run(
            [
                "python3", "-c",
                f"""
import whisper, sys
model = whisper.load_model("base", device="cuda")
result = model.transcribe("{audio_path}", language="{language}", fp16=True)
text = result["text"].strip().lower()
# reCAPTCHA audio = sequência de dígitos/palavras em inglês
# Limpar pontuação e espaços extras
import re
text = re.sub(r'[^a-z0-9 ]', '', text).strip()
print(text)
"""
            ],
            capture_output=True,
            timeout=30,
            cwd=os.environ.get("HOME", "/root"),
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


def _kill_orphan(profile_name: str):
    subprocess.run(["pkill", "-9", "-f", f"profiles/{profile_name}"], capture_output=True, timeout=5)
    time.sleep(0.3)


def _clean_locks(profile_dir: Path):
    for lk in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        try:
            (profile_dir / lk).unlink(missing_ok=True)
        except Exception:
            pass


def solve_recaptcha_v2_single(
    url: str,
    profile_name: str = "recaptcha",
    display: str = ":120",
    ns: str = "",
    timeout: int = 60,
    post_nav_js: str = "",
) -> str:
    """
    Uma tentativa de resolver reCAPTCHA v2 via audio+Whisper.
    Retorna token ou string vazia.
    """
    ns_label = ns or "host"
    profile_dir = PROFILE_BASE / profile_name
    _kill_orphan(profile_name)
    _clean_locks(profile_dir)

    log(f"[{ns_label}] Abrindo {url}")

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
            "node", str(SOLVER_JS), url, str(profile_dir), post_nav_js,
        ]
    else:
        cmd = ["node", str(SOLVER_JS), url, str(profile_dir), post_nav_js]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=os.environ.get("HOME", "/root"),
        )

        start = time.time()
        token = ""

        while time.time() - start < timeout:
            # Read line from stdout (non-blocking with timeout)
            try:
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                    continue

                msg = json.loads(line.decode().strip())
                status = msg.get("status", "")

                if status == "auto_solved":
                    token = msg.get("token", "")
                    log(f"[{ns_label}] Auto-solved! {len(token)} chars")
                    break

                elif status == "solved":
                    token = msg.get("token", "")
                    log(f"[{ns_label}] Solved via audio! {len(token)} chars")
                    break

                elif status == "audio_challenge":
                    audio_file = msg.get("audio_file", "")
                    log(f"[{ns_label}] Audio challenge: {audio_file}")

                    # Whisper transcribe
                    answer = whisper_transcribe(audio_file)
                    if answer:
                        # Send answer back to Node
                        response = json.dumps({"answer": answer}) + "\n"
                        proc.stdin.write(response.encode())
                        proc.stdin.flush()
                        log(f"[{ns_label}] Resposta enviada: '{answer}'")
                    else:
                        log(f"[{ns_label}] Whisper falhou, sem resposta")
                        proc.stdin.write(b'{"answer":""}\n')
                        proc.stdin.flush()

                elif status == "challenge_blocked":
                    log(f"[{ns_label}] Google bloqueou audio challenge")
                    break

                elif status == "error":
                    log(f"[{ns_label}] Erro: {msg.get('error', '?')}")
                    break

                elif status == "failed":
                    log(f"[{ns_label}] Falhou: {msg.get('error', '?')}")
                    break

            except json.JSONDecodeError:
                continue
            except Exception as e:
                log(f"[{ns_label}] Read erro: {e}")
                break

        # Cleanup
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

        return token

    except Exception as e:
        log(f"[{ns_label}] Erro geral: {e}")
        return ""


def solve_recaptcha_v2(
    url: str,
    profile_name: str = "recaptcha",
    display: str = ":120",
    post_nav_js: str = "",
) -> str:
    """
    Resolve reCAPTCHA v2 com rotação automática de namespace.
    Tenta até MAX_RETRIES vezes, rotacionando IP.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        ns_idx = (attempt - 1) % len(NAMESPACES)
        ns = NAMESPACES[ns_idx]
        ns_label = ns or "host"

        log(f"[Tentativa {attempt}/{MAX_RETRIES}] NS={ns_label}")

        token = solve_recaptcha_v2_single(
            url=url,
            profile_name=profile_name,
            display=display,
            ns=ns,
            post_nav_js=post_nav_js,
        )

        if token:
            log(f"Sucesso na tentativa {attempt} via {ns_label}")
            return token

        delay = min(attempt, 5)
        log(f"Falhou via {ns_label}, rotacionando em {delay}s...")
        time.sleep(delay)

    log(f"TODAS {MAX_RETRIES} tentativas falharam!")
    return ""


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Local reCAPTCHA v2 Solver (Audio + Whisper)")
    p.add_argument("url", help="URL da página com reCAPTCHA")
    p.add_argument("--profile", default="recaptcha", help="Nome do profile Chrome")
    p.add_argument("--display", default=":120", help="Display X11")
    p.add_argument("--post-nav-js", default="", help="JS to run after page load (e.g. submit form)")
    a = p.parse_args()

    token = solve_recaptcha_v2(a.url, profile_name=a.profile, display=a.display, post_nav_js=a.post_nav_js)
    if token:
        print(f"TOKEN ({len(token)} chars): {token[:80]}...")
    else:
        print("FALHOU")
        sys.exit(1)

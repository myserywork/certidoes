#!/usr/bin/env python3
"""
STF SPA Explorer — Python orchestrator (Whisper + Node stdin/stdout protocol)
Resolve WAF, mapeia SPA, salva resultado em /tmp/stf_spa_map.json
"""
import json, os, subprocess, sys, time
from pathlib import Path

SOLVER_JS = Path(__file__).parent / "stf_full_solver.js"

def log(msg):
    print(f"[STF-ORCH][{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)

def whisper_transcribe(audio_path):
    """Transcreve audio AWS WAF com Whisper medium."""
    log(f"Whisper transcrevendo: {audio_path}")
    wav_path = audio_path.rsplit(".", 1)[0] + ".wav"
    try:
        subprocess.run(["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", wav_path],
                      capture_output=True, timeout=10)
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
print("RAW: " + text, file=sys.stderr)
lower = text.lower()
if "by me" in lower:
    after = lower.split("by me")[-1].strip()
    parts = [p.strip() for p in after.replace(".", " ").replace(",", " ").split() if p.strip()]
    noise = {{"the","a","an","is","are","was","were","of","and","to","in","for","from","which","that","this","not","but","its","with","has","been","will","can","may","must","also"}}
    words = [w for w in parts if w.lower() not in noise and len(w) > 2 and w.isalpha()]
    print(words[0].lower() if words else text.split()[-1].lower())
elif "spoken" in lower:
    after = lower.split("spoken")[-1].strip()
    parts = [p.strip() for p in after.replace(".", " ").replace(",", " ").split() if p.strip()]
    noise = {{"the","a","an","is","are","was","were","of","and","to","in","for","from","which","that","this","not","but","its","with","has","been","will","can","may","must","also","by","me"}}
    words = [w for w in parts if w.lower() not in noise and len(w) > 2 and w.isalpha()]
    print(words[0].lower() if words else text.split()[-1].lower())
else:
    clean = re.sub(r'[^a-z0-9 ]', '', lower).strip()
    print(clean.split()[-1] if clean else "unknown")
"""],
            capture_output=True, timeout=45, cwd="/home/ramza",
        )
        text = result.stdout.decode().strip()
        stderr = result.stderr.decode()
        for line in stderr.strip().split("\n"):
            if line.strip():
                log(f"  Whisper: {line.strip()}")
        if text:
            log(f"Whisper resultado: '{text}'")
            return text
        return ""
    except Exception as e:
        log(f"Whisper erro: {e}")
        return ""

def run_explorer(cpf_cnpj="", display=":121"):
    env = os.environ.copy()
    env["DISPLAY"] = display
    env["HOME"] = "/home/ramza"
    env["NODE_PATH"] = "/home/ramza/node_modules"

    cmd = ["node", str(SOLVER_JS), cpf_cnpj, "explore"]
    log(f"Launching: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, cwd="/home/ramza",
    )

    results = []
    start = time.time()
    timeout = 120

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
            log(f"Node: {status}")

            if status == "audio_challenge":
                audio_file = msg.get("audio_file", "")
                answer = whisper_transcribe(audio_file)
                if answer:
                    response = json.dumps({"answer": answer}) + "\n"
                    proc.stdin.write(response.encode())
                    proc.stdin.flush()
                    log(f"Resposta enviada: '{answer}'")
                else:
                    proc.stdin.write(b'{"answer":""}\n')
                    proc.stdin.flush()

            elif status == "spa_mapped":
                log("SPA mapeada!")
                results.append(msg)
                # Save to file
                with open("/tmp/stf_spa_map.json", "w") as f:
                    json.dump(msg.get("data", {}), f, indent=2, ensure_ascii=False)

            elif status == "page_state":
                log(f"Page state received")
                results.append(msg)

            elif status in ("complete", "error", "no_captcha", "waf_solved"):
                results.append(msg)
                if status in ("complete", "error"):
                    break

        except json.JSONDecodeError:
            continue
        except Exception as e:
            log(f"Erro: {e}")
            break

    try:
        proc.kill()
    except Exception:
        pass

    # Log stderr
    try:
        stderr = proc.stderr.read().decode(errors="replace")
        for line in stderr.strip().split("\n")[-20:]:
            if line.strip():
                log(f"  {line.strip()}")
    except Exception:
        pass

    return results

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--cpf", default="")
    p.add_argument("--display", default=":121")
    a = p.parse_args()

    results = run_explorer(cpf_cnpj=a.cpf, display=a.display)
    print(json.dumps(results, indent=2, ensure_ascii=False))

#!/usr/bin/env python3
"""
TST CNDT Captcha Solver — Audio captcha + Whisper (100% local)

The TST CNDT uses a custom audio captcha that dictates letters/numbers
in Portuguese format: "Y W 3 V de bola F de faca V de vaca"

Parse rules:
  - Single letters/numbers are literal: "Y" → Y, "3" → 3
  - "X de Y" format: the FIRST letter before "de" is what we want,
    BUT we need to handle B/V disambiguation:
    - "B de bola" → B  (NOT "V de bola" which Whisper might mishear)
    - "V de vaca" → V
    - "F de faca" → F
    - "S de sapo" → S
    - "D de dado" → D
    - "P de pato" → P
    - "T de tatu" → T
    etc.

Usage:
    from infra.tst_captcha_solver import solve_tst_captcha
    result = solve_tst_captcha(cpf_cnpj, display=":121")
"""
import json
import os
import re
import subprocess
import sys
import time
import base64
from pathlib import Path

SOLVER_JS = Path(__file__).parent / "tst_captcha_solver.js"
MAX_RETRIES = 4
NAMESPACES = ["", "ns_t0", "ns_t1", "ns_t2", "ns_t3", "ns_t4"]

# ─── Phonetic alphabet mapping (Brazilian style) ─────────────
# "X de WORD" → the letter that WORD represents
PHONETIC_MAP = {
    # The WORD after "de" determines the letter
    "abelha": "A", "amor": "A", "aviao": "A", "arvore": "A",
    "bola": "B", "boi": "B", "barco": "B", "banana": "B", "burro": "B",
    "casa": "C", "cachorro": "C", "carro": "C", "cobra": "C", "cavalo": "C",
    "dado": "D", "dedo": "D", "doce": "D",
    "escola": "E", "elefante": "E", "estrela": "E",
    "faca": "F", "fogo": "F", "feira": "F", "foca": "F",
    "gato": "G", "gelo": "G", "galinha": "G",
    "hotel": "H", "heroi": "H",
    "igreja": "I", "ilha": "I",
    "janela": "J", "jogo": "J",
    "kilo": "K",
    "lua": "L", "leao": "L", "livro": "L", "lata": "L",
    "macaco": "M", "mesa": "M", "mala": "M", "mato": "M",
    "navio": "N", "nuvem": "N", "novo": "N",
    "ovo": "O", "ouro": "O",
    "pato": "P", "pai": "P", "porta": "P", "peixe": "P",
    "queijo": "Q",
    "rato": "R", "rio": "R", "rosa": "R", "rei": "R",
    "sapo": "S", "sol": "S", "sal": "S", "saco": "S",
    "tatu": "T", "terra": "T", "tigre": "T", "toca": "T",
    "uva": "U", "urso": "U",
    "vaca": "V", "vela": "V", "vento": "V", "verde": "V",
    "xadrez": "X", "xicara": "X",
    "zebra": "Z", "zero": "Z",
}

# Reverse: also handle "LETTER de WORD" where Whisper gives the letter
LETTER_WORDS = {
    "a": "A", "b": "B", "c": "C", "d": "D", "e": "E", "f": "F",
    "g": "G", "h": "H", "i": "I", "j": "J", "k": "K", "l": "L",
    "m": "M", "n": "N", "o": "O", "p": "P", "q": "Q", "r": "R",
    "s": "S", "t": "T", "u": "U", "v": "V", "w": "W", "x": "X",
    "y": "Y", "z": "Z",
}


def log(msg):
    print(f"[TSTCAP][{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def normalize_text(text):
    """Remove accents and normalize."""
    import unicodedata
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return text.lower().strip()


def parse_captcha_audio(whisper_text: str) -> str:
    """
    Parse Whisper output of TST captcha audio into the answer string.
    
    Input: "Y W 3 V de bola F de faca V de vaca"
    Output: "YW3BFV"
    """
    text = normalize_text(whisper_text)
    log(f"Parsing: '{text}'")
    
    result = []
    
    # Strategy 1: Find "X de WORD" patterns first
    # Replace them with the correct letter
    processed = text
    
    # Find all "X de WORD" patterns
    de_pattern = re.findall(r'(\w+)\s+de\s+(\w+)', processed)
    for letter_part, word_part in de_pattern:
        # Look up the word in phonetic map
        mapped = PHONETIC_MAP.get(word_part, "")
        if mapped:
            log(f"  '{letter_part} de {word_part}' → {mapped}")
            # Replace in processed text
            processed = processed.replace(f"{letter_part} de {word_part}", f" {mapped} ", 1)
        else:
            # If word not in map, use the first letter of letter_part
            letter = letter_part.upper()[0] if letter_part else ""
            log(f"  '{letter_part} de {word_part}' → {letter} (unmapped word)")
            processed = processed.replace(f"{letter_part} de {word_part}", f" {letter} ", 1)
    
    # Now process remaining tokens
    tokens = processed.split()
    for token in tokens:
        token = token.strip().strip('.,;:')
        if not token:
            continue
        
        # Single digit
        if token.isdigit():
            result.append(token)
            continue
        
        # Single letter
        if len(token) == 1 and token.isalpha():
            result.append(token.upper())
            continue
        
        # Two-letter combos that are actually separate letters
        if len(token) == 2 and token.isalpha():
            # Could be like "yw" which is Y W
            result.append(token[0].upper())
            result.append(token[1].upper())
            continue
        
        # Numbers written as words
        number_words = {
            "zero": "0", "um": "1", "dois": "2", "tres": "3", "quatro": "4",
            "cinco": "5", "seis": "6", "sete": "7", "oito": "8", "nove": "9",
        }
        if token in number_words:
            result.append(number_words[token])
            continue
        
        # Skip noise words
        if token in ["de", "e", "como", "a", "o", "ponto", "espaco", "virgula"]:
            continue
        
        # For longer tokens, take first letter (probably Whisper noise)
        if len(token) > 2:
            # Skip entirely — probably a transcription artifact
            log(f"  Skipping noise: '{token}'")
            continue
    
    answer = "".join(result)
    log(f"Parsed answer: '{answer}'")
    return answer


def transcribe_audio(audio_path: str, model_name: str = "medium") -> str:
    """Run Whisper on audio file."""
    log(f"Whisper transcribing: {audio_path} (model={model_name})")
    
    try:
        result = subprocess.run(
            ["python3", "-c", f"""
import whisper
model = whisper.load_model("{model_name}")
result = model.transcribe("{audio_path}", language="pt")
print(result["text"])
"""],
            capture_output=True, timeout=60, cwd=os.environ.get("HOME", "/root"),
        )
        text = result.stdout.decode().strip()
        stderr = result.stderr.decode(errors="replace")
        if stderr:
            for line in stderr.strip().split("\n")[-3:]:
                if line.strip():
                    log(f"  whisper: {line.strip()}")
        log(f"Whisper result: '{text}'")
        return text
    except subprocess.TimeoutExpired:
        log("Whisper timeout!")
        return ""
    except Exception as e:
        log(f"Whisper error: {e}")
        return ""


def solve_tst_single(cpf_cnpj: str, display: str = ":121", ns: str = "",
                     timeout_s: int = 120) -> dict:
    """Single attempt to solve TST CNDT captcha and get certidão."""
    ns_label = ns or "host"
    log(f"[{ns_label}] Starting for CPF/CNPJ: {cpf_cnpj}")
    
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
            "node", str(SOLVER_JS), cpf_cnpj,
        ]
    else:
        cmd = ["node", str(SOLVER_JS), cpf_cnpj]
    
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, cwd=os.environ.get("HOME", "/root"),
        )
        
        start = time.time()
        result = None
        
        while time.time() - start < timeout_s:
            try:
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                    continue
                
                msg = json.loads(line.decode().strip())
                status = msg.get("status", "")
                
                if status == "audio":
                    audio_path = msg.get("path", "")
                    attempt = msg.get("attempt", 1)
                    log(f"[{ns_label}] Audio captcha (attempt {attempt}): {audio_path}")
                    
                    # Transcribe with Whisper
                    text = transcribe_audio(audio_path, model_name="medium")
                    if not text:
                        # Try with small model as fallback
                        text = transcribe_audio(audio_path, model_name="small")
                    
                    if text:
                        answer = parse_captcha_audio(text)
                        if answer:
                            response = json.dumps({"answer": answer}) + "\n"
                            proc.stdin.write(response.encode())
                            proc.stdin.flush()
                            log(f"[{ns_label}] Sent answer: '{answer}'")
                        else:
                            proc.stdin.write(b'{"answer":""}\n')
                            proc.stdin.flush()
                    else:
                        proc.stdin.write(b'{"answer":""}\n')
                        proc.stdin.flush()
                    
                    # Clean up audio file
                    try:
                        os.remove(audio_path)
                    except:
                        pass
                
                elif status == "success":
                    log(f"[{ns_label}] Success!")
                    # Decode HTML from base64
                    html_b64 = msg.get("html_b64", "")
                    html = base64.b64decode(html_b64).decode("utf-8", errors="replace") if html_b64 else ""
                    result = {
                        "status": "sucesso",
                        "html": html,
                        "url": msg.get("url", ""),
                        "pdf_url": msg.get("pdf_url", ""),
                        "can_download": msg.get("can_download", ""),
                    }
                    break
                
                elif status == "error":
                    log(f"[{ns_label}] Error: {msg.get('error', '?')}")
                    break
                
                elif status == "failed":
                    log(f"[{ns_label}] Failed: {msg.get('error', '?')}")
                    break
                
                elif status == "page_loaded":
                    log(f"[{ns_label}] Page loaded, captcha={msg.get('has_captcha')}")
                
            except json.JSONDecodeError:
                continue
            except Exception as e:
                log(f"[{ns_label}] Read error: {e}")
                break
        
        try:
            proc.kill()
        except:
            pass
        
        try:
            stderr = proc.stderr.read().decode(errors="replace")
            for line in stderr.strip().split("\n"):
                if line.strip():
                    log(f"  {line.strip()}")
        except:
            pass
        
        return result or {"status": "erro", "mensagem": "No result from solver"}
    
    except Exception as e:
        log(f"[{ns_label}] Error: {e}")
        return {"status": "erro", "mensagem": str(e)}


def solve_tst_captcha(cpf_cnpj: str, display: str = ":121") -> dict:
    """Solve TST CNDT captcha with namespace rotation."""
    for attempt in range(1, MAX_RETRIES + 1):
        ns = NAMESPACES[(attempt - 1) % len(NAMESPACES)]
        ns_label = ns or "host"
        log(f"[Attempt {attempt}/{MAX_RETRIES}] NS={ns_label}")
        
        result = solve_tst_single(cpf_cnpj, display=display, ns=ns)
        if result.get("status") == "sucesso":
            log(f"Success on attempt {attempt} via {ns_label}")
            return result
        
        # Kill orphan chrome
        try:
            subprocess.run(
                "for pid in $(ps aux | grep chrome | grep -v grep | grep -v profiles_v15 | awk '{print $2}'); do kill -9 $pid 2>/dev/null; done",
                shell=True, timeout=5,
            )
        except:
            pass
        
        delay = min(attempt * 2, 5)
        log(f"Failed via {ns_label}, rotating in {delay}s...")
        time.sleep(delay)
    
    log(f"ALL {MAX_RETRIES} attempts failed!")
    return {"status": "erro", "mensagem": "All attempts failed"}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="TST CNDT Captcha Solver")
    p.add_argument("cpf_cnpj", help="CPF or CNPJ")
    p.add_argument("--display", default=":121")
    a = p.parse_args()
    
    result = solve_tst_captcha(a.cpf_cnpj, display=a.display)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])

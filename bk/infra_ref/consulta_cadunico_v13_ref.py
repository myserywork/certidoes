#!/usr/bin/env python3
"""
CadUnico Pipeline v13 — Puppeteer Token Farm + API Pública (sem JWT)
====================================================================

Arquitetura:
  - 5 workers, cada um em ns_t0..ns_t4
  - Cada worker roda token_farm.js (Puppeteer-stealth, Chrome persistente)
  - Token gerado -> curl API pública diretamente (sem JWT!)
  - Quando IP queima -> reload page (não mata Chrome)
  - Quando muitos fails -> rotaciona VPN server
  
Velocidade esperada: ~2-3 tokens/min por worker = 10-15 CPFs/min total
vs v12: ~3.5 CPFs/min total (30x mais lento)

Uso:
  python3 consulta_cadunico_v13.py maio [-w 5] [--max 1000]
  python3 consulta_cadunico_v13.py --list
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import signal
import urllib.parse
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field

import pandas as pd
import requests as _requests

# --- CONFIG ---
TG_TOKEN = "7647903493:AAG7XNy4AWdFM2rXECzmrmh2gJrrhbLC9oo"
TG_CHAT = "7613807585"

def tg(msg):
    """Send Telegram notification (fire and forget)."""
    try:
        _requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=5,
        )
    except:
        pass
CRED_DIR = Path("/home/ramza/credenciais_cadunico")
PROC_DIR = CRED_DIR / "processing_rj"
SOURCE_PROFILE = CRED_DIR / "google_profile_logged"
PROFILE_DIR = CRED_DIR / "profiles_v13"
OUTPUT_DIR = CRED_DIR / "lotes_v13"
TOKEN_FARM = Path("/home/ramza/token_farm.js")
VERIFIED_POOL = Path("/home/ramza/mullvad_wg/verified_servers.json")

API_BASE = "https://cadunico.dataprev.gov.br/transacional/api/transacional-api/v1/pessoa"
API_HEADERS = [
    "-H", "Accept: application/json",
    "-H", "CnasVersao: 1.35.01",
    "-H", "Origin: https://cadunico.dataprev.gov.br",
    "-H", "Referer: https://cadunico.dataprev.gov.br/",
]

NAMESPACES = ["ns_t0", "ns_t1", "ns_t2", "ns_t3", "ns_t4"]
DISPLAYS = [":99", ":100", ":101", ":102", ":103"]

MAX_WORKERS = 5
FLUSH_EVERY = 50
MAX_CONSECUTIVE_FAILS = 5  # reload page after this many
MAX_API_FAILS = 10  # rotate VPN after this many
VPN_ROTATE_CMD = "/usr/local/bin/vpn-rotate"

MONTH_FILES = {
    "marco": "agenda_65anos_2026_RJ_marco.parquet",
    "abril": "agenda_65anos_2026_RJ_abril.parquet",
    "maio": "agenda_65anos_2026_RJ_maio.parquet",
    "junho": "agenda_65anos_2026_RJ_junho.parquet",
    "julho": "agenda_65anos_2026_RJ_julho.parquet",
    "agosto": "agenda_65anos_2026_RJ_agosto.parquet",
    "setembro": "agenda_65anos_2026_RJ_setembro.parquet",
    "outubro": "agenda_65anos_2026_RJ_outubro.parquet",
    "novembro": "agenda_65anos_2026_RJ_novembro.parquet",
    "dezembro": "agenda_65anos_2026_RJ_dezembro.parquet",
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}]{msg}", flush=True)


@dataclass
class WorkerStats:
    ok: int = 0
    err: int = 0
    tokens: int = 0
    token_fail: int = 0
    api_fail: int = 0
    reloads: int = 0
    vpn_rotates: int = 0
    start_time: float = field(default_factory=time.time)


class TokenFarmWorker:
    """Manages a single token_farm.js process in a VPN namespace."""
    
    def __init__(self, worker_id: int, ns: str, display: str):
        self.wid = worker_id
        self.ns = ns
        self.display = display
        self.profile = PROFILE_DIR / f"w{worker_id}"
        self.proc = None
        self.stats = WorkerStats()
        self.consecutive_token_fails = 0
        self.consecutive_api_fails = 0
    
    def _log(self, msg):
        log(f"[W{self.wid}] {msg}")
    
    async def start(self):
        """Start token_farm.js in namespace."""
        # Garantir diretório pai
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        # Clean profile
        if self.profile.exists():
            subprocess.run(["rm", "-rf", str(self.profile)], capture_output=True)
        # Clean locks
        for lk in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
            try: (self.profile / lk).unlink(missing_ok=True)
            except: pass
        
        self._log(f"Starting token_farm in {self.ns} display={self.display}")
        self.proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", "ip", "netns", "exec", self.ns,
            "sudo", "-u", "ramza",
            "env", f"DISPLAY={self.display}", "HOME=/home/ramza", "NODE_TLS_REJECT_UNAUTHORIZED=0",
            "node", str(TOKEN_FARM),
            "--profile", str(self.profile),
            "--source-profile", str(SOURCE_PROFILE),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        
        # Wait for ready
        try:
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=45)
            d = json.loads(line.decode().strip())
            if d.get("ok"):
                self._log("Chrome ready!")
                return True
            else:
                self._log(f"Chrome failed: {d}")
                return False
        except asyncio.TimeoutError:
            self._log("Chrome open TIMEOUT")
            return False
        except Exception as e:
            self._log(f"Chrome open error: {e}")
            return False
    
    async def stop(self):
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.stdin.write(b'{"cmd":"quit"}\n')
                await self.proc.stdin.drain()
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except:
                try: self.proc.kill()
                except: pass
        self.proc = None
    
    async def _send_cmd(self, cmd: dict, timeout=30) -> dict:
        if not self.proc or self.proc.returncode is not None:
            return {"ok": False, "error": "proc_dead"}
        try:
            self.proc.stdin.write((json.dumps(cmd) + "\n").encode())
            await self.proc.stdin.drain()
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=timeout)
            if not line:
                return {"ok": False, "error": "empty_response"}
            return json.loads(line.decode().strip())
        except asyncio.TimeoutError:
            return {"ok": False, "error": "timeout"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    async def gen_token(self) -> str:
        resp = await self._send_cmd({"cmd": "gen"}, timeout=50)
        if resp.get("ok") and resp.get("token"):
            self.stats.tokens += 1
            self.consecutive_token_fails = 0
            return resp["token"]
        self.stats.token_fail += 1
        self.consecutive_token_fails += 1
        return ""
    
    async def reload_page(self):
        self._log("Reloading page...")
        self.stats.reloads += 1
        resp = await self._send_cmd({"cmd": "reload"}, timeout=25)
        self.consecutive_token_fails = 0
        return resp.get("ok", False)
    
    async def restart(self):
        """Full restart: kill Chrome + relaunch."""
        self._log("Full restart...")
        await self.stop()
        await asyncio.sleep(1)
        return await self.start()
    
    async def rotate_vpn(self):
        """Rotate VPN server for this namespace."""
        self._log(f"Rotating VPN for {self.ns}...")
        self.stats.vpn_rotates += 1
        try:
            r = await asyncio.create_subprocess_exec(
                "sudo", "-n", VPN_ROTATE_CMD, "rotate", self.ns,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(r.wait(), timeout=20)
            self._log("VPN rotated")
            self.consecutive_api_fails = 0
        except Exception as e:
            self._log(f"VPN rotate error: {e}")
    
    async def call_api(self, cpf: str, dn: str, token: str) -> dict:
        """Call DATAPREV API via namespace (no JWT needed)."""
        url = f"{API_BASE}/{cpf}/cadunico?dataNascimento={dn}&captchaResponse={urllib.parse.quote(token)}"
        
        try:
            r = await asyncio.create_subprocess_exec(
                "sudo", "-n", "ip", "netns", "exec", self.ns,
                "curl", "-s", "--max-time", "15",
                "-w", "\n---HTTP:%{http_code}",
                url, *API_HEADERS,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(r.communicate(), timeout=20)
            output = stdout.decode()
            
            # Parse response
            lines = output.strip().split("\n")
            http_line = [l for l in lines if l.startswith("---HTTP:")]
            http_code = int(http_line[0].split(":")[1]) if http_line else 0
            body = "\n".join(l for l in lines if not l.startswith("---HTTP:"))
            
            result = {"http_code": http_code, "body": body}
            
            try:
                data = json.loads(body)
                result["data"] = data
            except:
                pass
            
            if http_code == 200:
                self.consecutive_api_fails = 0
            elif http_code in (403, 429):
                self.consecutive_api_fails += 1
            
            return result
            
        except asyncio.TimeoutError:
            self.consecutive_api_fails += 1
            return {"http_code": 0, "body": "timeout"}
        except Exception as e:
            self.consecutive_api_fails += 1
            return {"http_code": 0, "body": str(e)}
    
    async def process_cpf(self, cpf: str, dn: str) -> dict:
        """Full cycle: gen token -> call API -> reload page -> return result.
        
        CRITICAL: Each token is SINGLE-USE. Must reload page after each API call.
        """
        
        # Check if we need full restart
        if self.consecutive_token_fails >= MAX_CONSECUTIVE_FAILS:
            ok = await self.restart()
            if not ok:
                return {"cpf": cpf, "status": "worker_dead", "http_code": 0}
        
        if self.consecutive_api_fails >= MAX_API_FAILS:
            await self.rotate_vpn()
            await self.restart()
        
        # Gen token
        token = await self.gen_token()
        if not token:
            # Reload e tentar mais uma vez
            await self.reload_page()
            token = await self.gen_token()
            if not token:
                return {"cpf": cpf, "status": "token_fail", "http_code": 0}
        
        # Call API
        api_result = await self.call_api(cpf, dn, token)
        http_code = api_result.get("http_code", 0)
        data = api_result.get("data", {})
        body = api_result.get("body", "")
        
        # Token é SINGLE-USE — reload page para próximo token
        await self.reload_page()
        
        # Classify result
        if http_code == 200:
            self.stats.ok += 1
            if data.get("usuarioCadUnico") is True:
                return {"cpf": cpf, "status": "cadastrado", "http_code": 200, "data": data}
            elif data.get("usuarioCadUnico") is False:
                return {"cpf": cpf, "status": "nao_cadastrado", "http_code": 200}
            else:
                return {"cpf": cpf, "status": "cadastrado", "http_code": 200, "data": data}
        
        elif http_code == 403:
            self.stats.err += 1
            codigo = data.get("mensagemErro", {}).get("codigo", "")
            descricao = data.get("mensagemErro", {}).get("descricao", "")
            
            if codigo == "41":  # "Esse CPF não foi encontrado"
                self.stats.ok += 1  # Count as success
                return {"cpf": cpf, "status": "nao_cadastrado", "http_code": 403}
            elif codigo == "04":  # "CPF informado é inválido"
                self.stats.ok += 1
                return {"cpf": cpf, "status": "cpf_invalido", "http_code": 400}
            elif "captcha" in descricao.lower():
                return {"cpf": cpf, "status": "captcha_invalid", "http_code": 403}
            else:
                return {"cpf": cpf, "status": f"err_{codigo}", "http_code": 403, "error": descricao}
        
        else:
            self.stats.err += 1
            return {"cpf": cpf, "status": f"http_{http_code}", "http_code": http_code, "error": body[:200]}


async def worker_loop(worker: TokenFarmWorker, cpf_queue: asyncio.Queue, results: list, stop_event: asyncio.Event):
    """Worker loop: pull CPFs from queue, process, push results."""
    while not stop_event.is_set():
        try:
            cpf, dn = cpf_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        
        result = await worker.process_cpf(cpf, dn)
        results.append(result)
        
        status = result["status"]
        http = result["http_code"]
        worker._log(f"{cpf} -> {status} (HTTP {http})")
    
    await worker.stop()


def load_pending_cpfs(month: str, max_cpfs: int = 0) -> list:
    """Load pending CPFs from parquet."""
    filename = MONTH_FILES.get(month)
    if not filename:
        print(f"Mês '{month}' não encontrado. Use --list")
        sys.exit(1)
    
    filepath = PROC_DIR / filename
    if not filepath.exists():
        print(f"Arquivo não encontrado: {filepath}")
        sys.exit(1)
    
    df = pd.read_parquet(filepath)
    
    # Filter pending (no result yet)
    pending = df[df["cadunico_result"].isna() | (df["cadunico_result"] == "")]
    log(f"Loaded {len(pending)}/{len(df)} pending CPFs from {month}")
    
    cpfs = []
    for _, row in pending.iterrows():
        cpf = str(row["idoso_cpf"]).zfill(11)
        dn_raw = str(row["idoso_nascimento"])  # já vem DD-MM-AAAA do parquet
        # Limpar e reformatar para garantir DD-MM-AAAA
        import re as _re
        dn_digits = _re.sub(r"\D", "", dn_raw)
        if len(dn_digits) == 8:
            dn = f"{dn_digits[:2]}-{dn_digits[2:4]}-{dn_digits[4:]}"
        else:
            dn = dn_raw
        if len(cpf) == 11 and len(dn) >= 10:
            cpfs.append((cpf, dn))
    
    if max_cpfs > 0:
        cpfs = cpfs[:max_cpfs]
    
    return cpfs


def save_results(results: list, month: str):
    """Save results to parquet and CSV."""
    if not results:
        return
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # CSV backup
    csv_path = OUTPUT_DIR / f"v13_{ts}.csv"
    with open(csv_path, "w") as f:
        f.write("cpf,status,http_code\n")
        for r in results:
            f.write(f"{r['cpf']},{r['status']},{r['http_code']}\n")
    log(f"CSV saved: {csv_path} ({len(results)} records)")
    
    # Merge into parquet
    filename = MONTH_FILES.get(month)
    if not filename:
        return
    filepath = PROC_DIR / filename
    
    try:
        df = pd.read_parquet(filepath)
        result_map = {r["cpf"]: r for r in results}
        
        updated = 0
        for idx, row in df.iterrows():
            cpf = str(row["idoso_cpf"]).zfill(11)
            if cpf in result_map:
                r = result_map[cpf]
                df.at[idx, "cadunico_result"] = r["status"]
                df.at[idx, "last_status_code"] = float(r["http_code"])
                df.at[idx, "processed_at"] = datetime.now().isoformat()
                df.at[idx, "attempts"] = (row.get("attempts") or 0) + 1
                if r.get("error"):
                    df.at[idx, "last_error"] = str(r["error"])[:200]
                updated += 1
        
        df.to_parquet(filepath, index=False)
        log(f"[MERGE] Updated {updated} records in {filepath.name}")
    except Exception as e:
        log(f"[MERGE] ERROR: {e}")


async def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("month", nargs="?", help="Month to process")
    p.add_argument("-w", "--workers", type=int, default=5)
    p.add_argument("--max", type=int, default=0)
    p.add_argument("--list", action="store_true")
    args = p.parse_args()
    
    if args.list:
        for month, fname in MONTH_FILES.items():
            fpath = PROC_DIR / fname
            if fpath.exists():
                df = pd.read_parquet(fpath)
                done = len(df[df["cadunico_result"].notna() & (df["cadunico_result"] != "")])
                print(f"  {month:12s} {done:6d}/{len(df):6d} ({len(df)-done} pending)")
        return
    
    if not args.month:
        print("Usage: python3 consulta_cadunico_v13.py <month> [-w 5] [--max 1000]")
        return
    
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Load CPFs
    cpfs = load_pending_cpfs(args.month, args.max)
    if not cpfs:
        log("Nenhum CPF pendente!")
        return
    
    num_workers = min(args.workers, len(cpfs), MAX_WORKERS)
    log(f"=== Pipeline v13 | {args.month} | {len(cpfs)} CPFs | {num_workers} workers ===")
    tg(f"🚀 <b>Pipeline v13 iniciado</b>\n{args.month} | {len(cpfs)} CPFs | {num_workers} workers")
    
    # Create queue
    queue = asyncio.Queue()
    for cpf, dn in cpfs:
        queue.put_nowait((cpf, dn))
    
    # Start workers
    workers = []
    for i in range(num_workers):
        w = TokenFarmWorker(i, NAMESPACES[i], DISPLAYS[i])
        ok = await w.start()
        if ok:
            workers.append(w)
        else:
            log(f"[W{i}] Failed to start, retrying...")
            await asyncio.sleep(2)
            ok = await w.start()
            if ok:
                workers.append(w)
            else:
                log(f"[W{i}] SKIPPED (Chrome won't start)")
    
    if not workers:
        log("FATAL: No workers started!")
        return
    
    log(f"{len(workers)} workers active")
    
    # Run
    results = []
    stop_event = asyncio.Event()
    t0 = time.time()
    
    # Handle Ctrl+C
    def signal_handler(sig, frame):
        log("\nCtrl+C! Saving results...")
        stop_event.set()
    signal.signal(signal.SIGINT, signal_handler)
    
    # Launch worker loops
    tasks = [
        asyncio.create_task(worker_loop(w, queue, results, stop_event))
        for w in workers
    ]
    
    # Progress monitor
        async def monitor():
            last_save = 0
            last_tg = 0
            while not all(t.done() for t in tasks):
                await asyncio.sleep(30)
                elapsed = time.time() - t0
                total_ok = sum(1 for r in results if r["status"] in ("cadastrado", "nao_cadastrado", "cpf_invalido"))
                rate = total_ok / (elapsed / 60) if elapsed > 0 else 0
                pending_q = queue.qsize()
                log(f"[PROGRESS] {len(results)} done ({total_ok} ok) | {pending_q} pending | {rate:.1f}/min")
                
                # Telegram a cada 500 resultados
                if total_ok - last_tg >= 500:
                    cad = sum(1 for r in results if r["status"] == "cadastrado")
                    tg(f"📊 <b>Progresso v13</b>\n✅ {total_ok}/{len(cpfs)} ({100*total_ok/len(cpfs):.1f}%)\nCadastrados: {cad}\nVelocidade: {rate:.1f}/min\nPendentes: {pending_q}")
                    last_tg = total_ok
                
                # Flush periodically
                if len(results) - last_save >= FLUSH_EVERY:
                    save_results(results, args.month)
                    last_save = len(results)
    
    monitor_task = asyncio.create_task(monitor())
    
    await asyncio.gather(*tasks)
    monitor_task.cancel()
    
    # Final save
    elapsed = time.time() - t0
    save_results(results, args.month)
    
    # Stats
    total_ok = sum(1 for r in results if r["status"] in ("cadastrado", "nao_cadastrado", "cpf_invalido"))
    total_err = len(results) - total_ok
    rate = total_ok / (elapsed / 60) if elapsed > 0 else 0
    
    log(f"\n{'='*60}")
    log(f"  DONE {elapsed:.0f}s ({elapsed/60:.1f}min)")
    log(f"  OK: {total_ok} | Err: {total_err} | Total: {len(results)}")
    log(f"  Rate: {rate:.1f}/min")
    cad = sum(1 for r in results if r["status"] == "cadastrado")
    nao = sum(1 for r in results if r["status"] == "nao_cadastrado")
    for w in workers:
        s = w.stats
        log(f"  W{w.wid}: ok={s.ok} err={s.err} tok={s.tokens} tfail={s.token_fail} reloads={s.reloads} vpn_rot={s.vpn_rotates}")
    log(f"{'='*60}")
    tg(f"🏁 <b>Pipeline v13 finalizado</b>\n{args.month} | {elapsed/60:.1f}min\n✅ OK: {total_ok} | ❌ Err: {total_err}\n📋 Cadastrados: {cad} | Não: {nao}\n⚡ {rate:.1f}/min")


if __name__ == "__main__":
    asyncio.run(main())

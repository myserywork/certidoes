#!/usr/bin/env python3
"""
Worker v2 — Consome tasks individuais (1 certidao por vez).

Cada task na fila eh "{job_id}:{cert_id}".
Qualquer worker pega qualquer task.
4 workers = 4x mais rapido (auto-balanceado).

Uso:
    python3 -m api.worker                        # default
    python3 -m api.worker --max-chrome 10        # mais Chrome
    python3 -m api.worker --id worker-srv1       # nome customizado
"""
import sys
import os
import json
import time
import signal
import threading
import traceback
import argparse
import requests as http_requests
from pathlib import Path
from datetime import datetime

import redis as redis_lib

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from api.jobs import get_redis, get_job, save_job, QUEUE_KEY, _job_key, CACHE_TTL
from api.logger import get_logger
import api.chrome_patch

# ─── Config ───────────────────────────────────────────────
MAX_CHROME = int(os.environ.get("MAX_CHROME", "4"))
WORKER_ID = os.environ.get("WORKER_ID", f"worker-{os.getpid()}")
DOWNLOADS_DIR = PROJECT_ROOT / "api" / "downloads"
CERT_TIMEOUT = 120

_shutdown = threading.Event()
_chrome_sem = None
_log = get_logger("worker")


# ─── Import scripts ──────────────────────────────────────

_script_cache = {}

def _import_script(filename):
    if filename in _script_cache:
        return _script_cache[filename]
    import importlib.util
    filepath = PROJECT_ROOT / f"{filename}.py"
    if not filepath.exists():
        raise FileNotFoundError(f"Script nao encontrado: {filepath}")
    module_name = f"_worker_{filename.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, str(filepath))
    mod = importlib.util.module_from_spec(spec)
    mod.__name__ = module_name
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    _script_cache[filename] = mod
    return mod

def _nav(script_name, args):
    mod = _import_script(script_name)
    bot = mod.Navegador(headless=False)
    try:
        resultado = bot.emitir_certidao(*args)
        bot.fechar()
        if not resultado:
            return {"status": "falha", "mensagem": "Certidao nao disponivel"}
        if isinstance(resultado, dict):
            resp = dict(resultado)
            if "status" in resp and resp["status"] not in ("sucesso", "erro", "falha", "parcial"):
                resp["resultado_texto"] = resp["status"]
                resp["status"] = "sucesso" if resp.get("link") else "falha"
            elif "status" not in resp:
                resp["status"] = "sucesso" if resp.get("link") else "falha"
            if not resp.get("link"):
                resp["status"] = "falha"
                resp.setdefault("mensagem", "PDF nao gerado")
            return resp
        return {"status": "sucesso", "link": resultado}
    except Exception as e:
        try:
            bot.fechar()
        except Exception:
            pass
        return {"status": "erro", "mensagem": str(e)[:500]}


# ─── Runners ──────────────────────────────────────────────

def run_receita_pj(p): return _nav("1-certidao_receita_pj", (p["cnpj"],))
def run_receita_pf(p): return _nav("2-certidao_receita_pf", (p["cpf"], p["dt_nascimento"]))
def run_stj_pf(p): return _nav("4-certidao_STJ_pf", (p["cpf"],))
def run_stj_pj(p): return _nav("5-certidao_STJ_pj", (p["cnpj"],))
def run_tjgo_civil(p): return _nav("6-certidao_civil_tjgo_pf", (p["nome"], p["cpf"], p["nm_mae"], p["dt_nascimento"]))
def run_tjgo_processos(p): return _nav("7-consulta_processos_tjgo_pj", (p.get("cpf") or p.get("cnpj"),))
def run_tjgo_criminal(p): return _nav("8-certidao_criminal_tjgo_pf", (p["nome"], p["cpf"], p["nm_mae"], p["dt_nascimento"]))
def run_trf1_cpf(p):
    for tp in ["criminal", "civil"]:
        r = _nav("9-certidao_TRF1_todos", (tp, "cpf", p["cpf"]))
        if r.get("status") == "sucesso": return r
    return r
def run_trf1_cnpj(p): return _nav("9-certidao_TRF1_todos", ("criminal", "cnpj", p["cnpj"]))
def run_tcu(p):
    mod = _import_script("11-certidao_TCU")
    return mod.emitir_certidao_tcu(p.get("cpf") or p.get("cnpj"))
def run_mpf(p):
    mod = _import_script("13-certidao_MPF")
    return mod.emitir_certidao_mpf(p.get("cpf") or p.get("cnpj"), "F" if p.get("cpf") else "J")
def run_trt18(p): return _nav("15-certidao_TRT18", (p.get("cpf") or p.get("cnpj"), "andamento"))
def run_ibama(p):
    mod = _import_script("16-certidao_IBAMA")
    return mod.emitir_certidao_ibama(p.get("cpf") or p.get("cnpj"))
def run_tst_cndt(p):
    mod = _import_script("17-certidao_TST_CNDT")
    return mod.emitir_cndt(p.get("cpf") or p.get("cnpj"))
def run_mpgo(p):
    mod = _import_script("18-certidao_MPGO")
    return mod.emitir_certidao_mpgo(p.get("cpf") or p.get("cnpj"))

RUNNERS = {
    "receita-pj": run_receita_pj, "receita-pf": run_receita_pf,
    "stj-pf": run_stj_pf, "stj-pj": run_stj_pj,
    "tjgo-civil": run_tjgo_civil, "tjgo-processos": run_tjgo_processos,
    "tjgo-criminal": run_tjgo_criminal,
    "trf1-cpf": run_trf1_cpf, "trf1-cnpj": run_trf1_cnpj,
    "tcu": run_tcu, "mpf": run_mpf, "trt18": run_trt18,
    "ibama": run_ibama, "tst-cndt": run_tst_cndt, "mpgo": run_mpgo,
}


# ─── Helpers ──────────────────────────────────────────────

def _sanitize(result):
    if not isinstance(result, dict):
        return {"status": "erro", "mensagem": "retorno invalido"}
    return {k: v for k, v in result.items()
            if not (k == "resultado" and isinstance(v, str) and len(v) > 500) and k != "pdf_local"}

def _cache_key(tipo, doc, cert_id):
    return f"pedro:cache:{tipo}:{doc}:{cert_id}"

def _download_pdf(job_id, cert_id, url):
    if not url: return None
    try:
        resp = http_requests.get(url.replace("tmpfiles.org/", "tmpfiles.org/dl/"), timeout=30)
        if resp.status_code == 200 and len(resp.content) > 100:
            d = DOWNLOADS_DIR / job_id
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{cert_id}.pdf").write_bytes(resp.content)
            return f"downloads/{job_id}/{cert_id}.pdf"
    except Exception:
        pass
    return None


# ─── Parecer ──────────────────────────────────────────────

CERT_NOMES = {
    "receita-pj": "Receita Federal PJ", "receita-pf": "Receita Federal PF",
    "stj-pf": "STJ Pessoa Fisica", "stj-pj": "STJ Pessoa Juridica",
    "tcu": "TCU (Tribunal de Contas)", "mpf": "MPF (Ministerio Publico Federal)",
    "trt18": "TRT18 (Trabalho GO)", "ibama": "IBAMA (Ambiental)",
    "tst-cndt": "TST CNDT (Debitos Trabalhistas)", "mpgo": "MPGO (Ministerio Publico GO)",
    "tjgo-processos": "TJGO Processos", "tjgo-civil": "TJGO Civel",
    "tjgo-criminal": "TJGO Criminal", "trf1-cpf": "TRF1", "trf1-cnpj": "TRF1",
}

def _gerar_parecer(job):
    certs = job.get("certidoes", {})
    total = len(certs)
    suc = fal = 0
    detalhes, alertas = [], []
    for cid, c in certs.items():
        nome = CERT_NOMES.get(cid, c.get("nome", cid))
        s = c.get("status", "pendente")
        res = c.get("resultado") or {}
        if s in ("sucesso", "cache"):
            suc += 1
            tc = res.get("tipo_certidao", "")
            if tc == "nada_consta": detalhes.append(f"{nome}: NADA CONSTA")
            elif tc in ("consta", "positiva"):
                detalhes.append(f"{nome}: {tc.upper()}")
                alertas.append(f"{nome}: {tc.upper()}")
            else:
                detalhes.append(f"{nome}: emitida" + (" (PDF)" if res.get("link") else "") + (" (cache)" if s == "cache" else ""))
        else:
            fal += 1
            detalhes.append(f"{nome}: FALHA - {(res.get('mensagem','') if res else '')[:60]}")

    sit = "regular" if fal == 0 and not alertas else "regular_com_ressalvas" if fal == 0 or suc >= total * 0.6 else "incompleto" if suc > 0 else "erro_total"
    return {"resumo": f"{suc} de {total} certidoes emitidas", "situacao": sit,
            "sucesso": suc, "falha": fal, "alertas": alertas, "detalhes": detalhes}


# ─── Atualizar job no Redis (atomico) ────────────────────

def _update_job_cert(job_id, cert_id, updates):
    r = get_redis()
    key = _job_key(job_id)
    for _ in range(30):
        try:
            with r.pipeline() as pipe:
                pipe.watch(key)
                raw = pipe.get(key)
                if not raw: return
                job = json.loads(raw)
                if cert_id in job["certidoes"]:
                    job["certidoes"][cert_id].update(updates)
                # Recontar
                total = conc = suc = fal = 0
                for cd in job["certidoes"].values():
                    total += 1
                    s = cd.get("status", "pendente")
                    if s in ("sucesso", "sucesso_sem_pdf", "parcial", "cache"): conc += 1; suc += 1
                    elif s in ("erro", "falha"): conc += 1; fal += 1
                job.update({"total": total, "concluidas": conc, "sucesso": suc, "falha": fal,
                            "atualizado_em": datetime.now().isoformat()})
                if conc >= total and job["status"] != "concluido":
                    job["status"] = "concluido"
                    job["finalizado_em"] = datetime.now().isoformat()
                    job["parecer"] = _gerar_parecer(job)
                    get_logger(f"job.{job_id}").info(f"CONCLUIDO | {suc} ok / {fal} falha")
                elif job["status"] == "na_fila":
                    job["status"] = "processando"
                pipe.multi()
                pipe.setex(key, 86400 * 3, json.dumps(job, ensure_ascii=False))
                pipe.execute()
                return
        except redis_lib.WatchError:
            time.sleep(0.05)
    _log.warning(f"WATCH exhausted {key}:{cert_id}")


# ─── Processar 1 task ────────────────────────────────────

def process_task(job_id, cert_id):
    r = get_redis()
    cert_log = get_logger(f"cert.{cert_id}")
    job = get_job(job_id)
    if not job:
        _log.warning(f"Job {job_id} nao encontrado")
        return
    cd = job.get("certidoes", {}).get(cert_id)
    if not cd:
        return
    if cd["status"] in ("sucesso", "cache", "parcial"):
        return

    params = job.get("params", {})
    tipo = job.get("tipo", "cpf")
    documento = job.get("documento", "")
    runner = RUNNERS.get(cert_id)

    if not runner:
        _update_job_cert(job_id, cert_id, {"status": "erro", "fim": datetime.now().isoformat(),
                                           "resultado": {"status": "erro", "mensagem": f"Runner {cert_id} nao existe"}})
        return

    # Cache
    cached = r.get(_cache_key(tipo, documento, cert_id))
    if cached:
        cert_log.info(f"job={job_id} doc={documento} CACHE")
        _update_job_cert(job_id, cert_id, {"status": "cache", "inicio": datetime.now().isoformat(),
                                           "fim": datetime.now().isoformat(), "resultado": json.loads(cached)})
        return

    # Semaforo
    _update_job_cert(job_id, cert_id, {"status": "na_fila"})
    if not _chrome_sem.acquire(timeout=300):
        _update_job_cert(job_id, cert_id, {"status": "erro", "fim": datetime.now().isoformat(),
                                           "resultado": {"status": "erro", "mensagem": "Timeout slot Chrome"}})
        return

    inicio = datetime.now()
    _update_job_cert(job_id, cert_id, {"status": "executando", "inicio": inicio.isoformat(), "worker": WORKER_ID})
    cert_log.info(f"job={job_id} doc={documento} INICIANDO [{WORKER_ID}]")

    try:
        _result = [None]; _err = [None]; _done = threading.Event()
        def _run():
            try: _result[0] = runner(params)
            except Exception as e: _err[0] = e
            finally: _done.set()
        threading.Thread(target=_run, daemon=True).start()

        if not _done.wait(timeout=CERT_TIMEOUT):
            cert_log.error(f"job={job_id} TIMEOUT {CERT_TIMEOUT}s")
            _update_job_cert(job_id, cert_id, {"status": "erro", "fim": datetime.now().isoformat(),
                                               "resultado": {"status": "erro", "mensagem": f"Timeout ({CERT_TIMEOUT}s)"}})
            return

        if _err[0]: raise _err[0]
        resultado = _sanitize(_result[0] or {"status": "falha", "mensagem": "Vazio"})
        status = resultado.get("status", "erro")
        if status not in ("sucesso", "erro", "falha", "parcial") and resultado.get("link"):
            resultado["resultado_texto"] = status; resultado["status"] = "sucesso"; status = "sucesso"

        link = resultado.get("link")
        if link and status == "sucesso":
            local = _download_pdf(job_id, cert_id, link)
            if local:
                resultado["arquivo_local"] = local
                resultado["link_local"] = f"/api/v1/download/{job_id}/{cert_id}"

        elapsed = (datetime.now() - inicio).total_seconds()
        if status == "sucesso":
            cert_log.info(f"job={job_id} doc={documento} SUCESSO {elapsed:.0f}s [{WORKER_ID}]")
        else:
            cert_log.warning(f"job={job_id} doc={documento} {status.upper()} {elapsed:.0f}s [{WORKER_ID}]")

        _update_job_cert(job_id, cert_id, {"status": status, "fim": datetime.now().isoformat(), "resultado": resultado})
        if status in ("sucesso", "parcial"):
            r.setex(_cache_key(tipo, documento, cert_id), CACHE_TTL, json.dumps(resultado, ensure_ascii=False))

    except Exception as e:
        cert_log.error(f"job={job_id} EXCECAO: {e}", exc_info=True)
        _update_job_cert(job_id, cert_id, {"status": "erro", "fim": datetime.now().isoformat(),
                                           "resultado": {"status": "erro", "mensagem": str(e)[:500]}})
    finally:
        _chrome_sem.release()


# ─── Cleanup ──────────────────────────────────────────────

def _cleanup(r):
    for key in r.keys("pedro:job:*"):
        raw = r.get(key)
        if not raw: continue
        job = json.loads(raw)
        if job.get("status") == "na_fila" and job.get("total", 0) == 0:
            job["status"] = "cancelado"; job["finalizado_em"] = datetime.now().isoformat()
            r.setex(key, 86400 * 3, json.dumps(job, ensure_ascii=False))
        elif job.get("status") == "processando":
            try:
                if (datetime.now() - datetime.fromisoformat(job.get("criado_em", ""))).total_seconds() > 600:
                    for cd in job["certidoes"].values():
                        if cd.get("status") in ("executando", "na_fila", "pendente"):
                            cd["status"] = "erro"; cd["resultado"] = {"status": "erro", "mensagem": "Timeout global"}
                    suc = sum(1 for c in job["certidoes"].values() if c["status"] in ("sucesso", "cache"))
                    fal = sum(1 for c in job["certidoes"].values() if c["status"] in ("erro", "falha"))
                    job.update({"status": "concluido", "concluidas": suc + fal, "sucesso": suc, "falha": fal,
                                "finalizado_em": datetime.now().isoformat(), "parecer": _gerar_parecer(job)})
                    r.setex(key, 86400 * 3, json.dumps(job, ensure_ascii=False))
            except Exception: pass


# ─── Loop ─────────────────────────────────────────────────

def worker_loop():
    r = get_redis()
    _log.info(f"Worker {WORKER_ID} | chrome={MAX_CHROME} | fila={QUEUE_KEY}")
    r.sadd("pedro:workers:active", WORKER_ID)
    last_cleanup = 0
    threads = []

    while not _shutdown.is_set():
        try:
            if time.time() - last_cleanup > 60:
                _cleanup(r)
                threads = [t for t in threads if t.is_alive()]
                last_cleanup = time.time()

            result = r.brpop(QUEUE_KEY, timeout=5)
            if not result: continue
            _, task = result

            if ":" not in task:
                _log.warning(f"Task invalida: {task}")
                continue

            job_id, cert_id = task.split(":", 1)
            _log.info(f"Task: {job_id}:{cert_id}")

            t = threading.Thread(target=process_task, args=(job_id, cert_id), daemon=True)
            t.start()
            threads.append(t)

        except redis_lib.ConnectionError as e:
            _log.error(f"Redis: {e}"); time.sleep(5)
        except Exception as e:
            _log.error(f"Erro: {e}", exc_info=True); time.sleep(2)

    _log.info("Parando, aguardando tasks...")
    for t in threads:
        t.join(timeout=30)
    r.srem("pedro:workers:active", WORKER_ID)
    _log.info("Worker encerrado")


def main():
    global MAX_CHROME, WORKER_ID, _chrome_sem
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-chrome", type=int, default=int(os.environ.get("MAX_CHROME", "4")))
    parser.add_argument("--id", default=os.environ.get("WORKER_ID", None))
    args = parser.parse_args()
    MAX_CHROME = args.max_chrome
    if args.id: WORKER_ID = args.id
    _chrome_sem = threading.Semaphore(MAX_CHROME)

    signal.signal(signal.SIGINT, lambda s, f: (_log.info("SIGINT"), _shutdown.set()))
    signal.signal(signal.SIGTERM, lambda s, f: (_log.info("SIGTERM"), _shutdown.set()))
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n  PEDRO Worker v2 | {WORKER_ID} | chrome={MAX_CHROME}\n")
    worker_loop()

if __name__ == "__main__":
    main()

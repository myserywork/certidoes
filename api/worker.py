#!/usr/bin/env python3
"""
Worker de Certidoes — consome jobs da fila Redis e executa.

Uso:
    python3 -m api.worker                          # 1 worker, max 3 Chrome
    python3 -m api.worker --max-chrome 5            # mais Chrome simultaneos
    python3 -m api.worker --id worker-2             # nome customizado

Funcionalidades:
    - Consome fila Redis (BRPOP)
    - Executa certidoes em paralelo (semaforo limita Chrome)
    - Cache: se ja extraiu para o mesmo documento, pula
    - Parecer: gera resumo ao final do job
    - Download: salva PDFs localmente para servir via API
"""
import sys
import os
import json
import time
import signal
import threading
import traceback
import argparse
import shutil
import requests as http_requests
from pathlib import Path
from datetime import datetime

import redis as redis_lib

# Setup path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from api.jobs import get_redis, get_job, save_job, QUEUE_KEY, _job_key
from api.logger import get_logger
import api.chrome_patch  # Forca --no-sandbox no Chrome quando em Docker

# ─── Config ────────────────────────────────────────────────
MAX_CHROME = int(os.environ.get("MAX_CHROME", "3"))
WORKER_ID = os.environ.get("WORKER_ID", f"worker-{os.getpid()}")
DOWNLOADS_DIR = PROJECT_ROOT / "api" / "downloads"
CACHE_TTL = 86400  # 24h de cache

_shutdown = threading.Event()
_chrome_sem = None

_log = get_logger("worker")


def log(msg):
    _log.info(msg)


# ─── Importadores de scripts ──────────────────────────────

_script_cache = {}


def _import_script(filename: str):
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

def run_receita_pj(p):
    return _nav("1-certidao_receita_pj", (p["cnpj"],))

def run_receita_pf(p):
    return _nav("2-certidao_receita_pf", (p["cpf"], p["dt_nascimento"]))

def run_stj_pf(p):
    return _nav("4-certidao_STJ_pf", (p["cpf"],))

def run_stj_pj(p):
    return _nav("5-certidao_STJ_pj", (p["cnpj"],))

def run_tjgo_civil(p):
    return _nav("6-certidao_civil_tjgo_pf", (p["nome"], p["cpf"], p["nm_mae"], p["dt_nascimento"]))

def run_tjgo_processos(p):
    return _nav("7-consulta_processos_tjgo_pj", (p.get("cpf") or p.get("cnpj"),))

def run_tjgo_criminal(p):
    return _nav("8-certidao_criminal_tjgo_pf", (p["nome"], p["cpf"], p["nm_mae"], p["dt_nascimento"]))

def run_trf1_cpf(p):
    results = []
    for tp in ["criminal", "civil"]:
        r = _nav("9-certidao_TRF1_todos", (tp, "cpf", p["cpf"]))
        r["subtipo"] = tp
        results.append(r)
    for r in results:
        if r.get("status") == "sucesso":
            return r
    return results[-1] if results else {"status": "erro", "mensagem": "TRF1 sem resultado"}

def run_trf1_cnpj(p):
    return _nav("9-certidao_TRF1_todos", ("criminal", "cnpj", p["cnpj"]))

def run_tcu(p):
    mod = _import_script("11-certidao_TCU")
    return mod.emitir_certidao_tcu(p.get("cpf") or p.get("cnpj"))

def run_mpf(p):
    doc = p.get("cpf") or p.get("cnpj")
    tipo = "F" if p.get("cpf") else "J"
    mod = _import_script("13-certidao_MPF")
    return mod.emitir_certidao_mpf(doc, tipo)

def run_trt18(p):
    return _nav("15-certidao_TRT18", (p.get("cpf") or p.get("cnpj"), "andamento"))

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


# ─── Sanitizacao ──────────────────────────────────────────

def _sanitize(result: dict) -> dict:
    if not isinstance(result, dict):
        return {"status": "erro", "mensagem": "retorno invalido"}
    out = {}
    for k, v in result.items():
        if k == "resultado" and isinstance(v, str) and len(v) > 500:
            continue
        if k == "pdf_local":
            continue
        out[k] = v
    return out


# ─── Cache ────────────────────────────────────────────────

def _cache_key(tipo: str, documento: str, cert_id: str) -> str:
    return f"pedro:cache:{tipo}:{documento}:{cert_id}"


def _get_cache(r, tipo, documento, cert_id) -> dict | None:
    raw = r.get(_cache_key(tipo, documento, cert_id))
    if raw:
        return json.loads(raw)
    return None


def _set_cache(r, tipo, documento, cert_id, resultado: dict):
    r.setex(
        _cache_key(tipo, documento, cert_id),
        CACHE_TTL,
        json.dumps(resultado, ensure_ascii=False),
    )


# ─── Download local de PDFs ──────────────────────────────

def _download_pdf(job_id: str, cert_id: str, url: str) -> str | None:
    """Baixa PDF do tmpfiles e salva localmente. Retorna path relativo."""
    if not url:
        return None
    try:
        # tmpfiles.org retorna redirect para dl/
        dl_url = url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
        resp = http_requests.get(dl_url, timeout=30)
        if resp.status_code == 200 and len(resp.content) > 100:
            job_dir = DOWNLOADS_DIR / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{cert_id}.pdf"
            filepath = job_dir / filename
            filepath.write_bytes(resp.content)
            return f"downloads/{job_id}/{filename}"
    except Exception as e:
        log(f"  [{cert_id}] download local falhou: {e}")
    return None


# ─── Parecer ──────────────────────────────────────────────

PARECER_MAP = {
    "sucesso": "emitida",
    "erro": "falha na emissao",
    "falha": "indisponivel",
    "cache": "emitida (cache)",
}

CERTIDAO_NOMES = {
    "receita-pj": "Receita Federal PJ",
    "receita-pf": "Receita Federal PF",
    "stj-pf": "STJ Pessoa Fisica",
    "stj-pj": "STJ Pessoa Juridica",
    "tcu": "TCU (Tribunal de Contas)",
    "mpf": "MPF (Ministerio Publico Federal)",
    "trt18": "TRT18 (Trabalho GO)",
    "ibama": "IBAMA (Ambiental)",
    "tst-cndt": "TST CNDT (Debitos Trabalhistas)",
    "mpgo": "MPGO (Ministerio Publico GO)",
    "tjgo-processos": "TJGO Processos",
    "tjgo-civil": "TJGO Civel",
    "tjgo-criminal": "TJGO Criminal",
    "trf1-cpf": "TRF1 (1a Regiao)",
    "trf1-cnpj": "TRF1 (1a Regiao)",
}


def _gerar_parecer(job: dict) -> dict:
    """Gera parecer consolidado do job."""
    certidoes = job.get("certidoes", {})
    total = len(certidoes)
    sucesso = 0
    falha = 0
    detalhes = []
    alertas = []

    for cert_id, cert in certidoes.items():
        nome = CERTIDAO_NOMES.get(cert_id, cert.get("nome", cert_id))
        s = cert.get("status", "pendente")
        resultado = cert.get("resultado", {}) or {}

        if s in ("sucesso", "cache"):
            sucesso += 1
            tipo_cert = resultado.get("tipo_certidao", "")
            nome_pessoa = resultado.get("nome", "")

            if tipo_cert == "nada_consta":
                detalhes.append(f"{nome}: NADA CONSTA")
            elif tipo_cert == "consta":
                detalhes.append(f"{nome}: CONSTA (verificar)")
                alertas.append(f"{nome} retornou CONSTA")
            elif tipo_cert == "positiva":
                detalhes.append(f"{nome}: POSITIVA (verificar)")
                alertas.append(f"{nome} retornou certidao POSITIVA")
            else:
                link = resultado.get("link", "")
                detalhes.append(f"{nome}: emitida" + (f" (PDF)" if link else ""))
        else:
            falha += 1
            msg = resultado.get("mensagem", "falha") if resultado else "falha"
            detalhes.append(f"{nome}: FALHA - {msg[:60]}")

    # Situacao geral
    if falha == 0:
        if alertas:
            situacao = "regular_com_ressalvas"
        else:
            situacao = "regular"
    elif sucesso == 0:
        situacao = "erro_total"
    elif sucesso >= total * 0.6:
        situacao = "regular_com_ressalvas"
    else:
        situacao = "incompleto"

    return {
        "resumo": f"{sucesso} de {total} certidoes emitidas com sucesso",
        "situacao": situacao,
        "sucesso": sucesso,
        "falha": falha,
        "alertas": alertas,
        "detalhes": detalhes,
    }


# ─── Execucao de certidao (thread) ────────────────────────

def _execute_certidao(job_id: str, cert_id: str, params: dict, tipo: str, documento: str):
    r = get_redis()
    key = _job_key(job_id)
    runner = RUNNERS.get(cert_id)
    cert_log = get_logger(f"cert.{cert_id}")

    if not runner:
        cert_log.error(f"job={job_id} runner nao existe")
        _update_cert(r, key, cert_id, "erro", {"status": "erro", "mensagem": f"Runner {cert_id} nao existe"})
        _recount(r, key)
        return

    # Pular se ja em cache (pre-preenchido pelo create_job)
    raw = r.get(key)
    if raw:
        job_data = json.loads(raw)
        cert_data = job_data.get("certidoes", {}).get(cert_id, {})
        if cert_data.get("status") == "cache":
            _recount(r, key)
            return

    # Checar cache (fallback)
    cached = _get_cache(r, tipo, documento, cert_id)
    if cached:
        cert_log.info(f"job={job_id} doc={documento} CACHE HIT")
        cached["_from_cache"] = True
        _update_cert(r, key, cert_id, "cache", cached)
        _recount(r, key)
        return

    # Aguardar slot
    cert_log.debug(f"job={job_id} doc={documento} aguardando slot (semaforo)")
    _update_cert(r, key, cert_id, "na_fila")
    if not _chrome_sem.acquire(timeout=300):
        cert_log.error(f"job={job_id} doc={documento} TIMEOUT aguardando slot Chrome (300s)")
        _update_cert(r, key, cert_id, "erro",
                     {"status": "erro", "mensagem": "Timeout aguardando slot Chrome"},
                     fim=datetime.now().isoformat())
        _recount(r, key)
        return

    CERT_TIMEOUT = 120  # max 2 min por certidao

    inicio = datetime.now()
    cert_log.info(f"job={job_id} doc={documento} INICIANDO (timeout={CERT_TIMEOUT}s)")
    _update_cert(r, key, cert_id, "executando", inicio=inicio.isoformat())

    try:
        # Rodar com timeout: usa thread interna + Event
        _result_box = [None]
        _error_box = [None]
        _done = threading.Event()

        def _run_with_timeout():
            try:
                _result_box[0] = runner(params)
            except Exception as ex:
                _error_box[0] = ex
            finally:
                _done.set()

        t = threading.Thread(target=_run_with_timeout, daemon=True)
        t.start()

        if not _done.wait(timeout=CERT_TIMEOUT):
            # Timeout! Matar Chrome orfao desse cert
            cert_log.error(f"job={job_id} doc={documento} TIMEOUT ({CERT_TIMEOUT}s)")
            import subprocess
            subprocess.run(["pkill", "-f", f"chrome.*{cert_id}"], capture_output=True, timeout=5)
            _update_cert(r, key, cert_id, "erro",
                         {"status": "erro", "mensagem": f"Timeout ({CERT_TIMEOUT}s)"},
                         fim=datetime.now().isoformat())
            _chrome_sem.release()
            _recount(r, key)
            return

        if _error_box[0]:
            raise _error_box[0]

        resultado = _result_box[0]
        if resultado is None:
            resultado = {"status": "falha", "mensagem": "Runner retornou None"}
        resultado = _sanitize(resultado)

        status = resultado.get("status", "erro")
        if status not in ("sucesso", "erro", "falha", "parcial", "sucesso_sem_pdf"):
            if resultado.get("link"):
                resultado["resultado_texto"] = status
                resultado["status"] = "sucesso"
                status = "sucesso"

        # Baixar PDF local
        link = resultado.get("link")
        if link and status == "sucesso":
            local_path = _download_pdf(job_id, cert_id, link)
            if local_path:
                resultado["arquivo_local"] = local_path
                resultado["link_local"] = f"/api/v1/download/{job_id}/{cert_id}"

        elapsed = (datetime.now() - inicio).total_seconds()
        tipo_cert = resultado.get("tipo_certidao", "")
        nome_r = resultado.get("nome", "")

        if status == "sucesso":
            cert_log.info(
                f"job={job_id} doc={documento} SUCESSO em {elapsed:.1f}s"
                + (f" tipo={tipo_cert}" if tipo_cert else "")
                + (f" nome={nome_r[:40]}" if nome_r else "")
                + (f" link={link[:60]}" if link else "")
            )
        else:
            msg = resultado.get("mensagem", "")[:100]
            cert_log.warning(f"job={job_id} doc={documento} {status.upper()} em {elapsed:.1f}s | {msg}")

        _update_cert(r, key, cert_id, status, resultado, fim=datetime.now().isoformat())

        if status in ("sucesso", "parcial"):
            _set_cache(r, tipo, documento, cert_id, resultado)

    except Exception as e:
        elapsed = (datetime.now() - inicio).total_seconds()
        cert_log.error(f"job={job_id} doc={documento} EXCECAO em {elapsed:.1f}s: {str(e)[:200]}", exc_info=True)
        _update_cert(r, key, cert_id, "erro",
                     {"status": "erro", "mensagem": str(e)[:500]},
                     fim=datetime.now().isoformat())
    finally:
        _chrome_sem.release()

    _recount(r, key)


# ─── Redis updates (atomico) ──────────────────────────────

def _update_cert(r, key, cert_id, status, resultado=None, inicio=None, fim=None):
    for _ in range(20):
        try:
            with r.pipeline() as pipe:
                pipe.watch(key)
                raw = pipe.get(key)
                if not raw:
                    return
                job = json.loads(raw)
                if cert_id in job["certidoes"]:
                    job["certidoes"][cert_id]["status"] = status
                    if resultado is not None:
                        job["certidoes"][cert_id]["resultado"] = resultado
                    if inicio:
                        job["certidoes"][cert_id]["inicio"] = inicio
                    if fim:
                        job["certidoes"][cert_id]["fim"] = fim
                job["atualizado_em"] = datetime.now().isoformat()
                pipe.multi()
                pipe.setex(key, 86400 * 3, json.dumps(job, ensure_ascii=False))
                pipe.execute()
                return
        except redis_lib.WatchError:
            time.sleep(0.05)
            continue
    _log.warning(f"Redis WATCH exhausted after 20 retries for {key}")


def _recount(r, key):
    for _ in range(20):
        try:
            with r.pipeline() as pipe:
                pipe.watch(key)
                raw = pipe.get(key)
                if not raw:
                    return
                job = json.loads(raw)

                total = concluidas = sucesso = falha = 0
                for cd in job["certidoes"].values():
                    total += 1
                    s = cd.get("status", "pendente")
                    if s in ("sucesso", "sucesso_sem_pdf", "parcial", "cache"):
                        concluidas += 1
                        sucesso += 1
                    elif s in ("erro", "falha"):
                        concluidas += 1
                        falha += 1

                job["total"] = total
                job["concluidas"] = concluidas
                job["sucesso"] = sucesso
                job["falha"] = falha

                if concluidas >= total:
                    job["status"] = "concluido"
                    job["finalizado_em"] = datetime.now().isoformat()
                    job["parecer"] = _gerar_parecer(job)
                    jlog = get_logger(f"job.{job['job_id']}")
                    jlog.info(f"CONCLUIDO | {sucesso} ok / {falha} falha | parecer={job['parecer']['situacao']}")

                job["atualizado_em"] = datetime.now().isoformat()
                pipe.multi()
                pipe.setex(key, 86400 * 3, json.dumps(job, ensure_ascii=False))
                pipe.execute()
                return
        except redis_lib.WatchError:
            time.sleep(0.05)
            continue
    _log.warning(f"Redis WATCH exhausted after 20 retries for {key}")


# ─── Processamento de job ─────────────────────────────────

def process_job(job_id: str):
    r = get_redis()
    job = get_job(job_id)
    if not job:
        log(f"Job {job_id} nao encontrado, pulando")
        return

    tipo = job.get("tipo", "cpf")
    documento = job.get("documento", "")

    # Se o cliente mandou job sem certidoes preenchidas, preencher agora
    if not job.get("certidoes") or job.get("total", 0) == 0:
        from api.jobs import CPF_CERTIDOES, CPF_CERTIDOES_EXTRAS, CNPJ_CERTIDOES
        params = job.get("params", {})
        if tipo == "cpf":
            certs = list(CPF_CERTIDOES)
            for c in CPF_CERTIDOES_EXTRAS:
                if all(params.get(f) for f in c.get("requer", [])):
                    certs.append(c)
        else:
            certs = list(CNPJ_CERTIDOES)

        job["certidoes"] = {
            c["id"]: {"nome": c["nome"], "status": "pendente", "inicio": None, "fim": None, "resultado": None}
            for c in certs
        }
        job["total"] = len(certs)

    # Se mesmo assim ficou vazio, cancelar o job
    if not job.get("certidoes") or job.get("total", 0) == 0:
        job_log = get_logger(f"job.{job_id}")
        job_log.warning(f"CANCELADO | {tipo.upper()} {documento} | sem certidoes para executar (params invalidos?)")
        job["status"] = "cancelado"
        job["finalizado_em"] = datetime.now().isoformat()
        job["parecer"] = {"resumo": "Job cancelado - sem certidoes para executar", "situacao": "cancelado", "sucesso": 0, "falha": 0, "alertas": ["Documento ou parametros invalidos"], "detalhes": []}
        save_job(job)
        log(f"Job {job_id} cancelado (vazio)")
        return

    job_log = get_logger(f"job.{job_id}")
    job_log.info(f"INICIANDO | {tipo.upper()} {documento} | {job['total']} certidoes | worker={WORKER_ID}")
    log(f"Processando job {job_id} ({tipo.upper()} {documento}) - {job['total']} certidoes")

    job["status"] = "processando"
    job["worker_id"] = WORKER_ID
    job["iniciado_em"] = datetime.now().isoformat()
    save_job(job)

    params = job.get("params", {})
    threads = []

    for cert_id in job["certidoes"]:
        t = threading.Thread(
            target=_execute_certidao,
            args=(job_id, cert_id, params, tipo, documento),
            daemon=True,
            name=f"cert-{cert_id}",
        )
        threads.append(t)
        t.start()

    # Aguardar threads com timeout total de 5min
    deadline = time.time() + 300
    for t in threads:
        remaining = max(1, deadline - time.time())
        t.join(timeout=remaining)

    # Forcar conclusao de certidoes que ficaram pendentes/travadas
    key = _job_key(job_id)
    raw = r.get(key)
    if raw:
        job_check = json.loads(raw)
        fixed = 0
        for cid, cd in job_check.get("certidoes", {}).items():
            s = cd.get("status", "pendente")
            if s in ("executando", "na_fila", "pendente"):
                cd["status"] = "erro"
                cd["fim"] = datetime.now().isoformat()
                if s == "executando":
                    cd["resultado"] = {"status": "erro", "mensagem": "Timeout - certidao demorou demais"}
                else:
                    cd["resultado"] = {"status": "erro", "mensagem": "Worker finalizou antes de executar"}
                fixed += 1
        if fixed > 0:
            job_log.warning(f"Forcando {fixed} certidoes como erro (timeout/pendente)")
            r.setex(key, 86400 * 3, json.dumps(job_check, ensure_ascii=False))

    _recount(r, key)
    job_log.info(f"FINALIZADO | worker={WORKER_ID}")
    log(f"Job {job_id} finalizado")


# ─── Loop principal ───────────────────────────────────────

def _cleanup_stuck_jobs(r):
    """Limpa jobs travados ou vazios no Redis. Roda periodicamente."""
    keys = r.keys("pedro:job:*")
    fixed = 0
    for key in keys:
        raw = r.get(key)
        if not raw:
            continue
        job = json.loads(raw)
        jid = job.get("job_id", "?")
        status = job.get("status", "")
        total = job.get("total", 0)

        # Job vazio na_fila -> cancelar
        if status == "na_fila" and total == 0:
            job["status"] = "cancelado"
            job["finalizado_em"] = datetime.now().isoformat()
            job["parecer"] = {"resumo": "Cancelado - job vazio", "situacao": "cancelado",
                              "sucesso": 0, "falha": 0, "alertas": [], "detalhes": []}
            r.setex(key, 86400 * 3, json.dumps(job, ensure_ascii=False))
            _log.info(f"Cleanup: cancelado job vazio {jid}")
            fixed += 1

        # Job processando ha mais de 10min -> forcar conclusao
        elif status == "processando":
            iniciado = job.get("iniciado_em")
            if iniciado:
                try:
                    elapsed = (datetime.now() - datetime.fromisoformat(iniciado)).total_seconds()
                    if elapsed > 600:  # 10 min
                        for cid, cd in job.get("certidoes", {}).items():
                            s = cd.get("status", "pendente")
                            if s in ("executando", "na_fila", "pendente"):
                                cd["status"] = "erro"
                                cd["fim"] = datetime.now().isoformat()
                                cd["resultado"] = {"status": "erro", "mensagem": f"Timeout global ({int(elapsed)}s)"}

                        suc = sum(1 for c in job["certidoes"].values() if c["status"] in ("sucesso", "cache"))
                        fal = sum(1 for c in job["certidoes"].values() if c["status"] in ("erro", "falha"))
                        job["concluidas"] = suc + fal
                        job["sucesso"] = suc
                        job["falha"] = fal
                        job["status"] = "concluido"
                        job["finalizado_em"] = datetime.now().isoformat()
                        r.setex(key, 86400 * 3, json.dumps(job, ensure_ascii=False))
                        _log.warning(f"Cleanup: forcou conclusao job travado {jid} ({int(elapsed)}s)")
                        fixed += 1
                except Exception:
                    pass

    return fixed


def worker_loop():
    r = get_redis()
    log(f"Worker iniciado (max_chrome={MAX_CHROME})")
    log(f"Escutando fila: {QUEUE_KEY}")
    r.sadd("pedro:workers:active", WORKER_ID)

    last_cleanup = 0

    while not _shutdown.is_set():
        try:
            # Cleanup periodico (a cada 60s)
            now = time.time()
            if now - last_cleanup > 60:
                _cleanup_stuck_jobs(r)
                last_cleanup = now

            result = r.brpop(QUEUE_KEY, timeout=5)
            if result is None:
                continue
            _, job_id = result
            log(f"Job recebido: {job_id}")
            process_job(job_id)
        except redis_lib.ConnectionError as e:
            _log.error(f"Redis desconectou: {e}. Reconectando em 5s...")
            time.sleep(5)
        except Exception as e:
            _log.error(f"Erro no loop: {e}", exc_info=True)
            time.sleep(2)

    log("Aguardando jobs em andamento terminarem...")
    r.srem("pedro:workers:active", WORKER_ID)
    log("Worker encerrado")


def main():
    global MAX_CHROME, WORKER_ID, _chrome_sem

    parser = argparse.ArgumentParser(description="Worker de Certidoes")
    parser.add_argument("--max-chrome", type=int, default=3)
    parser.add_argument("--id", default=None)
    args = parser.parse_args()

    MAX_CHROME = args.max_chrome
    if args.id:
        WORKER_ID = args.id
    _chrome_sem = threading.Semaphore(MAX_CHROME)

    def _handle_signal(sig, frame):
        sig_name = signal.Signals(sig).name
        log(f"Sinal {sig_name} recebido. Iniciando shutdown graceful...")
        _shutdown.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"""
  Worker de Certidoes - PEDRO PROJECT
  ID: {WORKER_ID} | Max Chrome: {MAX_CHROME}
  Fila: {QUEUE_KEY} | Downloads: {DOWNLOADS_DIR}
  Aguardando jobs...
""")

    worker_loop()


if __name__ == "__main__":
    main()

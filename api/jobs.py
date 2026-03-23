"""
Jobs v2 — Arquitetura distribuida.

Cada certidao eh uma task independente na fila.
Qualquer worker pega qualquer task.
Job eh apenas um agrupador de tasks.

Redis keys:
  pedro:job:{job_id}           → JSON do job (status, certidoes, parecer)
  pedro:queue:tasks            → lista de tasks (FIFO): "{job_id}:{cert_id}"
  pedro:workers:active         → set de worker_ids
  pedro:cache:{tipo}:{doc}:{cert} → resultado cacheado
"""
import uuid
import json
import os
from datetime import datetime
from typing import Optional
from pathlib import Path

# Carregar .env automaticamente
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

import redis

# ─── Config ───────────────────────────────────────────────
REDIS_URL = os.environ.get("REDIS_URL", "")
JOB_TTL = 86400 * 3    # 3 dias
CACHE_TTL = 86400       # 24h
QUEUE_KEY = "pedro:queue:tasks"

_redis: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        for attempt in range(3):
            try:
                _redis = redis.from_url(REDIS_URL, decode_responses=True,
                                        socket_timeout=10, retry_on_timeout=True)
                _redis.ping()
                break
            except Exception:
                if attempt == 2:
                    raise
                import time
                time.sleep(1)
    return _redis


# ─── Certidoes por tipo ──────────────────────────────────

CPF_CERTIDOES = [
    {"id": "stj-pf", "nome": "STJ Pessoa Fisica"},
    {"id": "tcu", "nome": "TCU - Nada Consta"},
    {"id": "mpf", "nome": "MPF - Certidao Negativa"},
    {"id": "trt18", "nome": "TRT18 Goias"},
    {"id": "ibama", "nome": "IBAMA - Negativa de Debito"},
    {"id": "tst-cndt", "nome": "TST CNDT"},
    {"id": "mpgo", "nome": "MPGO"},
    {"id": "tjgo-processos", "nome": "TJGO Processos"},
]

CPF_CERTIDOES_EXTRAS = [
    {"id": "receita-pf", "nome": "Receita Federal PF", "requer": ["dt_nascimento"]},
    {"id": "tjgo-civil", "nome": "TJGO Civel PF", "requer": ["nome", "nm_mae", "dt_nascimento"]},
    {"id": "tjgo-criminal", "nome": "TJGO Criminal PF", "requer": ["nome", "nm_mae", "dt_nascimento"]},
    {"id": "trf1-cpf", "nome": "TRF1 (Criminal+Civil)", "requer": []},
]

CNPJ_CERTIDOES = [
    {"id": "receita-pj", "nome": "Receita Federal PJ"},
    {"id": "stj-pj", "nome": "STJ Pessoa Juridica"},
    {"id": "tcu", "nome": "TCU - Nada Consta"},
    {"id": "mpf", "nome": "MPF - Certidao Negativa"},
    {"id": "trt18", "nome": "TRT18 Goias"},
    {"id": "ibama", "nome": "IBAMA - Negativa de Debito"},
    {"id": "tst-cndt", "nome": "TST CNDT"},
    {"id": "mpgo", "nome": "MPGO"},
    {"id": "tjgo-processos", "nome": "TJGO Processos"},
    {"id": "trf1-cnpj", "nome": "TRF1 (Criminal)"},
]

# ─── Helpers ──────────────────────────────────────────────

def _job_key(job_id: str) -> str:
    return f"pedro:job:{job_id}"


def _cache_key(tipo: str, documento: str, cert_id: str) -> str:
    return f"pedro:cache:{tipo}:{documento}:{cert_id}"


# ─── Criar job ────────────────────────────────────────────

def create_job(params: dict) -> dict:
    """
    Cria job e publica cada certidao como task individual na fila.
    Certidoes em cache ja vem preenchidas.
    """
    r = get_redis()
    job_id = str(uuid.uuid4())[:8]
    is_cpf = bool(params.get("cpf"))
    tipo = "cpf" if is_cpf else "cnpj"
    documento = params.get("cpf") or params.get("cnpj")

    # Validar
    digitos = ''.join(c for c in (documento or '') if c.isdigit())
    if is_cpf and len(digitos) != 11:
        return {"erro": f"CPF invalido: {len(digitos)} digitos", "job_id": None}
    if not is_cpf and len(digitos) != 14:
        return {"erro": f"CNPJ invalido: {len(digitos)} digitos", "job_id": None}

    # Determinar certidoes
    if is_cpf:
        certidoes = list(CPF_CERTIDOES)
        for cert in CPF_CERTIDOES_EXTRAS:
            if all(params.get(c) for c in cert.get("requer", [])):
                certidoes.append(cert)
    else:
        certidoes = list(CNPJ_CERTIDOES)

    now = datetime.now().isoformat()
    cache_hits = 0
    certs_dict = {}
    tasks_to_queue = []

    for cert in certidoes:
        cid = cert["id"]
        cached = r.get(_cache_key(tipo, documento, cid))
        if cached:
            cache_hits += 1
            cached_data = json.loads(cached)
            cached_data["_from_cache"] = True
            certs_dict[cid] = {
                "nome": cert["nome"],
                "status": "cache",
                "inicio": now,
                "fim": now,
                "worker": None,
                "resultado": cached_data,
            }
        else:
            certs_dict[cid] = {
                "nome": cert["nome"],
                "status": "pendente",
                "inicio": None,
                "fim": None,
                "worker": None,
                "resultado": None,
            }
            tasks_to_queue.append(f"{job_id}:{cid}")

    total = len(certidoes)
    pendentes = len(tasks_to_queue)

    job = {
        "job_id": job_id,
        "status": "concluido" if pendentes == 0 else "na_fila",
        "tipo": tipo,
        "documento": documento,
        "params": params,
        "criado_em": now,
        "atualizado_em": now,
        "total": total,
        "concluidas": cache_hits,
        "sucesso": cache_hits,
        "falha": 0,
        "certidoes": certs_dict,
    }

    if pendentes == 0:
        job["finalizado_em"] = now
        job["parecer"] = {
            "resumo": f"{cache_hits} de {total} certidoes do cache (instantaneo)",
            "situacao": "regular",
            "sucesso": cache_hits, "falha": 0, "alertas": [], "detalhes": [],
        }

    # Salvar job
    r.setex(_job_key(job_id), JOB_TTL, json.dumps(job, ensure_ascii=False))

    # Publicar tasks individuais na fila
    if tasks_to_queue:
        r.lpush(QUEUE_KEY, *tasks_to_queue)

    return {
        "job_id": job_id,
        "status": job["status"],
        "total": total,
        "cache_hits": cache_hits,
        "pendentes": pendentes,
        "certidoes": [c["id"] for c in certidoes],
    }


# ─── Retry ────────────────────────────────────────────────

def retry_job(job_id: str) -> dict:
    """Re-enfileira certidoes que falharam como tasks individuais."""
    r = get_redis()
    job = get_job(job_id)
    if not job:
        return {"erro": "Job nao encontrado"}
    if job["status"] != "concluido":
        return {"erro": "Job ainda nao concluiu"}

    tasks_to_queue = []
    for cert_id, cert_data in job["certidoes"].items():
        if cert_data["status"] in ("erro", "falha"):
            cert_data["status"] = "pendente"
            cert_data["inicio"] = None
            cert_data["fim"] = None
            cert_data["worker"] = None
            cert_data["resultado"] = None
            tasks_to_queue.append(f"{job_id}:{cert_id}")

    if not tasks_to_queue:
        return {"retried": 0, "message": "Nenhuma certidao para reprocessar"}

    job["status"] = "processando"
    job["concluidas"] = job["sucesso"]
    job["falha"] = 0
    save_job(job)

    r.lpush(QUEUE_KEY, *tasks_to_queue)
    return {"retried": len(tasks_to_queue), "job_id": job_id, "status": "processando"}


# ─── Leitura ──────────────────────────────────────────────

def get_job(job_id: str) -> Optional[dict]:
    r = get_redis()
    raw = r.get(_job_key(job_id))
    return json.loads(raw) if raw else None


def save_job(job: dict):
    r = get_redis()
    job["atualizado_em"] = datetime.now().isoformat()
    r.setex(_job_key(job["job_id"]), JOB_TTL, json.dumps(job, ensure_ascii=False))


def list_jobs(limit: int = 50) -> list:
    r = get_redis()
    keys = r.keys("pedro:job:*")
    jobs = []
    for key in sorted(keys, reverse=True)[:limit]:
        raw = r.get(key)
        if raw:
            job = json.loads(raw)
            jobs.append({
                "job_id": job["job_id"],
                "status": job["status"],
                "tipo": job["tipo"],
                "documento": job["documento"],
                "total": job["total"],
                "concluidas": job["concluidas"],
                "sucesso": job["sucesso"],
                "falha": job["falha"],
                "criado_em": job["criado_em"],
            })
    return jobs


def delete_job(job_id: str) -> bool:
    r = get_redis()
    return r.delete(_job_key(job_id)) > 0


def queue_size() -> int:
    r = get_redis()
    return r.llen(QUEUE_KEY)

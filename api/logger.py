"""
Logger centralizado do PEDRO PROJECT.

Grava em:
  - Console (stderr)
  - logs/pedro.log          (tudo)
  - logs/jobs.log           (apenas jobs: criacao, progresso, conclusao)
  - logs/certidoes.log      (cada certidao: inicio, fim, resultado)
  - logs/erros.log          (apenas erros)

Uso:
    from api.logger import get_logger
    log = get_logger("worker")
    log.info("Job recebido: abc123")
    log.error("Falha no TCU", exc_info=True)
"""
import logging
import os
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

_initialized = False


def _setup_logging():
    """Configura logging uma unica vez."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    # Formato detalhado para arquivo
    file_fmt = logging.Formatter(
        "[%(asctime)s][%(name)s][%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Formato mais limpo para console
    console_fmt = logging.Formatter(
        "[%(name)s][%(asctime)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    root = logging.getLogger("pedro")
    root.setLevel(logging.DEBUG)

    # ─── Console (INFO+) ──────────────────────────────────
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_fmt)
    root.addHandler(console_handler)

    # ─── pedro.log (tudo) ─────────────────────────────────
    all_handler = logging.FileHandler(LOGS_DIR / "pedro.log", encoding="utf-8")
    all_handler.setLevel(logging.DEBUG)
    all_handler.setFormatter(file_fmt)
    root.addHandler(all_handler)

    # ─── jobs.log (apenas jobs) ───────────────────────────
    jobs_handler = logging.FileHandler(LOGS_DIR / "jobs.log", encoding="utf-8")
    jobs_handler.setLevel(logging.INFO)
    jobs_handler.setFormatter(file_fmt)
    jobs_handler.addFilter(lambda record: record.name.startswith("pedro.job"))
    root.addHandler(jobs_handler)

    # ─── certidoes.log (cada certidao) ────────────────────
    cert_handler = logging.FileHandler(LOGS_DIR / "certidoes.log", encoding="utf-8")
    cert_handler.setLevel(logging.INFO)
    cert_handler.setFormatter(file_fmt)
    cert_handler.addFilter(lambda record: record.name.startswith("pedro.cert"))
    root.addHandler(cert_handler)

    # ─── erros.log (WARNING+) ─────────────────────────────
    err_handler = logging.FileHandler(LOGS_DIR / "erros.log", encoding="utf-8")
    err_handler.setLevel(logging.WARNING)
    err_handler.setFormatter(file_fmt)
    root.addHandler(err_handler)


def get_logger(name: str) -> logging.Logger:
    """
    Retorna logger com nome 'pedro.{name}'.

    Exemplos:
        get_logger("api")         -> pedro.api
        get_logger("worker")      -> pedro.worker
        get_logger("job.abc123")  -> pedro.job.abc123   (grava em jobs.log)
        get_logger("cert.tcu")    -> pedro.cert.tcu     (grava em certidoes.log)
    """
    _setup_logging()
    return logging.getLogger(f"pedro.{name}")

"""
Utilitários compartilhados entre todos os extratores.
"""
import time
import sys
import requests
import tempfile
import os
import shutil


def log(tag: str, msg: str):
    """Log padronizado para todos os extratores."""
    print(f"[{tag}][{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def upload_para_tmpfiles(caminho_arquivo: str) -> str | None:
    """Upload para tmpfiles.org. Retorna URL ou None."""
    try:
        with open(caminho_arquivo, 'rb') as f:
            response = requests.post(
                'https://tmpfiles.org/api/v1/upload',
                files={'file': f},
                timeout=30,
            )
        if response.status_code == 200:
            link = response.json().get("data", {}).get("url")
            return link
        return None
    except Exception:
        return None


def resultado_erro(mensagem: str) -> dict:
    """Retorna dict padronizado de erro."""
    return {"status": "erro", "mensagem": mensagem}


def resultado_sucesso(**kwargs) -> dict:
    """Retorna dict padronizado de sucesso."""
    return {"status": "sucesso", **kwargs}

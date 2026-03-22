"""
Configuracoes globais da API de Certidoes.
"""
import os
import platform
from pathlib import Path

# Diretorio raiz do projeto (onde ficam os scripts 1-18)
PROJECT_ROOT = Path(__file__).parent.parent

# Detectar se estamos em Linux (WSL2) ou Windows
IS_LINUX = platform.system() == "Linux"

# Display X11 para scripts que usam browser
DISPLAY = os.environ.get("CAPTCHA_DISPLAY", os.environ.get("DISPLAY", ":121"))

# Porta padrao da API
API_PORT = int(os.environ.get("API_PORT", "8000"))

# Workers para execucao paralela de certidoes
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "4"))

# Timeout padrao por request (segundos)
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "120"))

# ─── Adaptacoes de ambiente ────────────────────────────────
if IS_LINUX:
    HOME_DIR = os.environ.get("HOME", "/root")
    NODE_PATH = os.environ.get("NODE_PATH", f"{HOME_DIR}/node_modules")
    os.environ.setdefault("HOME", HOME_DIR)
    os.environ.setdefault("NODE_PATH", NODE_PATH)
    os.environ.setdefault("DISPLAY", DISPLAY)
    os.environ.setdefault("CAPTCHA_DISPLAY", DISPLAY)
else:
    # Windows: NODE_PATH aponta para node_modules na pasta do projeto
    HOME_DIR = os.environ.get("USERPROFILE", str(PROJECT_ROOT))
    NODE_PATH = os.environ.get("NODE_PATH", str(PROJECT_ROOT / "node_modules"))
    os.environ.setdefault("NODE_PATH", NODE_PATH)

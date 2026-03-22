#!/bin/bash
# ============================================================
# start_api_wsl.sh — Inicia API + Worker dentro do WSL2
#
# Uso:
#   wsl -d Ubuntu-22.04 -- bash /mnt/c/.../start_api_wsl.sh
#   wsl -d Ubuntu-22.04 -- bash /mnt/c/.../start_api_wsl.sh --worker-only
#   wsl -d Ubuntu-22.04 -- bash /mnt/c/.../start_api_wsl.sh --api-only
# ============================================================

set -e

PROJECT_DIR="/mnt/c/Users/workstation/Desktop/PEDRO_PROJECT/PEDRO_PROJECT"
cd "${PROJECT_DIR}"

export DISPLAY=:121
export NODE_PATH=/root/node_modules
export HOME=/root
export CAPTCHA_DISPLAY=:121

MODE="${1:-all}"  # all | --api-only | --worker-only

# ─── Xvfb ─────────────────────────────────────────────────
if ! xdpyinfo -display :121 &>/dev/null; then
    Xvfb :121 -screen 0 1920x1080x24 -ac &>/dev/null &
    sleep 1
fi

# ─── VPN ───────────────────────────────────────────────────
NS_COUNT=$(ip netns list 2>/dev/null | wc -l)
if [ "$NS_COUNT" -lt 5 ]; then
    echo "[SETUP] Subindo VPN namespaces..."
    sed 's/\r$//' "${PROJECT_DIR}/setup_vpn_wsl2.sh" | bash 2>&1
fi

# ─── Limpar Chrome orfao ──────────────────────────────────
pkill -f "chrome.*puppeteer" 2>/dev/null || true
pkill -f "chrome.*headless" 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  PEDRO PROJECT — Certidoes Automatizadas             ║"
echo "║                                                      ║"
echo "║  API:     http://localhost:8000                      ║"
echo "║  Swagger: http://localhost:8000/docs                 ║"
echo "║  Fila:    GET /api/v1/queue                          ║"
echo "║                                                      ║"
echo "║  Modo: ${MODE}                                       ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

if [ "$MODE" = "--worker-only" ]; then
    echo "[WORKER] Iniciando worker..."
    python3 -m api.worker --max-chrome 3
elif [ "$MODE" = "--api-only" ]; then
    echo "[API] Iniciando API..."
    python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000
else
    # Iniciar API em background e worker em foreground
    echo "[API] Iniciando API em background..."
    python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 &
    API_PID=$!
    sleep 2

    echo "[WORKER] Iniciando worker..."
    python3 -m api.worker --max-chrome 3 &
    WORKER_PID=$!

    # Trap para matar ambos ao sair
    trap "kill $API_PID $WORKER_PID 2>/dev/null; exit" INT TERM

    # Aguardar ambos
    wait $API_PID $WORKER_PID
fi

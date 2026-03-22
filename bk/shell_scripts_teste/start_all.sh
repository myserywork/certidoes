#!/bin/bash
# ============================================================
# PEDRO PROJECT — Iniciar todos os serviços
# Roda dentro do WSL2: wsl -d Ubuntu-22.04 -e bash /root/pedro_project/start_all.sh
# ============================================================

set -e

export DISPLAY=:121
export NODE_PATH=/root/node_modules
export CHROME_PATH=/usr/bin/google-chrome
export PYTHONUNBUFFERED=1

PROJECT_DIR="/root/pedro_project"
LOG_DIR="/root/pedro_project/logs"
mkdir -p "${LOG_DIR}"

echo "============================================"
echo "  PEDRO PROJECT — Iniciando Serviços"
echo "============================================"

# 1. Xvfb
if ! pgrep -x Xvfb > /dev/null; then
    Xvfb :121 -screen 0 1920x1080x24 -ac &
    sleep 1
    echo "[OK] Xvfb :121 iniciado"
else
    echo "[OK] Xvfb já rodando"
fi

# 2. Verificar GPU
GPU_OK=$(python3 -c "import torch; print('yes' if torch.cuda.is_available() else 'no')" 2>/dev/null)
if [ "${GPU_OK}" = "yes" ]; then
    echo "[OK] GPU CUDA disponível"
else
    echo "[AVISO] GPU CUDA NÃO disponível — Whisper vai rodar em CPU (lento)"
fi

# 3. Matar processos antigos
pkill -f "certidao_TCU" 2>/dev/null || true
pkill -f "certidao_CPF_Receita" 2>/dev/null || true
pkill -f "certidao_MPF" 2>/dev/null || true
pkill -f "certidao_STF" 2>/dev/null || true
pkill -f "certidao_TRT18" 2>/dev/null || true
pkill -f "certidao_IBAMA" 2>/dev/null || true
pkill -f "certidao_TST_CNDT" 2>/dev/null || true
pkill -f "certidao_MPGO" 2>/dev/null || true
sleep 1

echo ""
echo "=== Iniciando APIs Flask ==="

cd "${PROJECT_DIR}"

# Scripts do Pedro (1-9) — porta 5000
# (rodar conforme necessário, aqui mostramos como exemplo)
# python3 1-certidao_receita_pj.py > "${LOG_DIR}/01_receita_pj.log" 2>&1 &

# Scripts 11-18
python3 11-certidao_TCU.py --serve --port 5011 > "${LOG_DIR}/11_tcu.log" 2>&1 &
echo "  [5011] TCU — PID $!"

python3 12-certidao_CPF_Receita.py --serve --port 5012 > "${LOG_DIR}/12_cpf_receita.log" 2>&1 &
echo "  [5012] CPF Receita — PID $!"

python3 13-certidao_MPF.py --serve --port 5013 > "${LOG_DIR}/13_mpf.log" 2>&1 &
echo "  [5013] MPF — PID $!"

python3 14-certidao_STF.py --serve --port 5014 > "${LOG_DIR}/14_stf.log" 2>&1 &
echo "  [5014] STF — PID $!"

python3 15-certidao_TRT18.py > "${LOG_DIR}/15_trt18.log" 2>&1 &
echo "  [5015] TRT18 — PID $!"

python3 16-certidao_IBAMA.py --serve --port 5016 > "${LOG_DIR}/16_ibama.log" 2>&1 &
echo "  [5016] IBAMA — PID $!"

python3 17-certidao_TST_CNDT.py --serve --port 5017 > "${LOG_DIR}/17_tst.log" 2>&1 &
echo "  [5017] TST CNDT — PID $!"

python3 18-certidao_MPGO.py --serve --port 5018 > "${LOG_DIR}/18_mpgo.log" 2>&1 &
echo "  [5018] MPGO — PID $!"

echo ""
echo "============================================"
echo "  Todos os serviços iniciados!"
echo "  Logs em: ${LOG_DIR}/"
echo ""
echo "  Testar: curl -X POST http://localhost:5011/certidao \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"cpf\": \"12345678900\"}'"
echo ""
echo "  Ver logs: tail -f ${LOG_DIR}/*.log"
echo "============================================"

# Manter script rodando (para os processos filhos)
wait

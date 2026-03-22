#!/bin/bash
# ============================================================
# PEDRO PROJECT — Setup automatico para maquina nova
#
# Requisitos: Ubuntu 22.04 com Docker instalado
#
# Uso:
#   # Maquina com GPU NVIDIA:
#   curl -sSL https://raw.githubusercontent.com/.../setup.sh | bash
#
#   # Ou localmente:
#   bash setup.sh
#   bash setup.sh --no-gpu        # maquina sem GPU
#   bash setup.sh --api            # so API (sem worker)
#   bash setup.sh --vpn wg0.conf   # com VPN
# ============================================================

set -e

MODE="worker-gpu"
VPN_CONF=""

for arg in "$@"; do
    case $arg in
        --no-gpu) MODE="worker-nogpu" ;;
        --api) MODE="api" ;;
        --vpn) shift; VPN_CONF="$1" ;;
    esac
done

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  PEDRO PROJECT — Setup Automatico            ║"
echo "║  Modo: $MODE"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ─── 1. Verificar Docker ─────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "[1/5] Instalando Docker..."
    curl -fsSL https://get.docker.com | bash
    systemctl enable docker
    systemctl start docker
else
    echo "[1/5] Docker OK: $(docker --version)"
fi

# ─── 2. NVIDIA Container Toolkit (se GPU) ────────────────
if [ "$MODE" = "worker-gpu" ] || [ "$MODE" = "worker-vpn" ]; then
    if ! command -v nvidia-smi &>/dev/null; then
        echo "[2/5] AVISO: nvidia-smi nao encontrado. Instale drivers NVIDIA primeiro."
        echo "       https://docs.nvidia.com/datacenter/tesla/tesla-installation-notes/"
        exit 1
    fi

    if ! dpkg -l | grep -q nvidia-container-toolkit; then
        echo "[2/5] Instalando NVIDIA Container Toolkit..."
        distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
            gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
        curl -s -L "https://nvidia.github.io/libnvidia-container/${distribution}/libnvidia-container.list" | \
            sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
            tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
        apt-get update && apt-get install -y nvidia-container-toolkit
        nvidia-ctk runtime configure --runtime=docker
        systemctl restart docker
    else
        echo "[2/5] NVIDIA Toolkit OK: $(nvidia-smi --query-gpu=name --format=csv,noheader)"
    fi
else
    echo "[2/5] Sem GPU, pulando NVIDIA toolkit"
fi

# ─── 3. Criar .env ───────────────────────────────────────
if [ ! -f .env ]; then
    echo "[3/5] Criando .env..."
    HOSTNAME_SHORT=$(hostname | cut -c1-12)

    # Calcular MAX_CHROME pela RAM
    TOTAL_RAM_GB=$(free -g | awk '/^Mem:/{print $2}')
    if [ "$TOTAL_RAM_GB" -ge 200 ]; then
        MAX_CHROME=50
    elif [ "$TOTAL_RAM_GB" -ge 100 ]; then
        MAX_CHROME=25
    elif [ "$TOTAL_RAM_GB" -ge 50 ]; then
        MAX_CHROME=12
    elif [ "$TOTAL_RAM_GB" -ge 20 ]; then
        MAX_CHROME=6
    else
        MAX_CHROME=3
    fi

    cat > .env << EOF
REDIS_URL=redis://default:tjp5bDfy2uU4P7RNKroDoxk0QeiyeXNX@redis-10074.c256.us-east-1-2.ec2.cloud.redislabs.com:10074
MAX_CHROME=${MAX_CHROME}
WORKER_ID=worker-${HOSTNAME_SHORT}
API_PORT=8000
EOF
    echo "       MAX_CHROME=$MAX_CHROME (baseado em ${TOTAL_RAM_GB}GB RAM)"
else
    echo "[3/5] .env ja existe"
fi

# ─── 4. VPN (opcional) ───────────────────────────────────
if [ -n "$VPN_CONF" ]; then
    echo "[4/5] Configurando VPN..."
    mkdir -p docker/vpn
    cp "$VPN_CONF" docker/vpn/
    echo "       Config copiada para docker/vpn/"
else
    echo "[4/5] Sem VPN configurada"
fi

# ─── 5. Build e Start ────────────────────────────────────
echo "[5/5] Buildando e iniciando..."
echo ""

case $MODE in
    api)
        docker compose build api
        docker compose up -d api
        echo ""
        echo "API rodando em http://$(hostname -I | awk '{print $1}'):8000"
        echo "Dashboard: http://$(hostname -I | awk '{print $1}'):8000/dashboard"
        ;;
    worker-gpu)
        docker compose build worker-gpu
        docker compose up -d worker-gpu
        echo ""
        echo "Worker GPU iniciado"
        docker compose logs --tail 5 worker-gpu
        ;;
    worker-nogpu)
        docker compose --profile nogpu build worker-nogpu
        docker compose --profile nogpu up -d worker-nogpu
        echo ""
        echo "Worker (sem GPU) iniciado"
        ;;
    worker-vpn)
        docker compose --profile vpn build worker-vpn
        docker compose --profile vpn up -d worker-vpn
        echo ""
        echo "Worker VPN iniciado"
        ;;
esac

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Setup concluido!                             ║"
echo "║                                              ║"
echo "║  Comandos uteis:                             ║"
echo "║    docker compose logs -f                    ║"
echo "║    docker compose ps                         ║"
echo "║    docker compose restart worker-gpu         ║"
echo "║    docker compose down                       ║"
echo "╚══════════════════════════════════════════════╝"

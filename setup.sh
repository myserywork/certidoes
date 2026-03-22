#!/bin/bash
# ============================================================
# PEDRO PROJECT — Setup Automatico
#
# Roda em qualquer Ubuntu 22.04+ fresh.
# Detecta hardware, instala tudo, configura e sobe.
#
# USO:
#   curl -sSL https://raw.githubusercontent.com/myserywork/certidoes/main/setup.sh | bash
#
#   # Ou com parametros:
#   curl -sSL .../setup.sh | bash -s -- --redis "redis://..." --vpn /path/wg0.conf
#   curl -sSL .../setup.sh | bash -s -- --api    # tambem sobe API nessa maquina
#   curl -sSL .../setup.sh | bash -s -- --no-gpu  # maquina sem NVIDIA
# ============================================================

set -e

# ─── Parametros ───────────────────────────────────────────
REDIS_URL=""
VPN_CONF=""
RUN_API=false
NO_GPU=false
REPO="https://github.com/myserywork/certidoes.git"
INSTALL_DIR="/opt/pedro"

for arg in "$@"; do
    case $arg in
        --redis) shift; REDIS_URL="$1"; shift ;;
        --vpn) shift; VPN_CONF="$1"; shift ;;
        --api) RUN_API=true ;;
        --no-gpu) NO_GPU=true ;;
        --dir) shift; INSTALL_DIR="$1"; shift ;;
        *) ;;
    esac
done

# ─── Banner ───────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  PEDRO PROJECT — Setup Automatico                    ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ─── Detectar hardware ────────────────────────────────────
echo "[1/7] Detectando hardware..."

TOTAL_RAM_GB=$(free -g 2>/dev/null | awk '/^Mem:/{print $2}' || echo 8)
CPU_CORES=$(nproc 2>/dev/null || echo 4)
HOSTNAME_SHORT=$(hostname | cut -c1-12)

HAS_NVIDIA=false
GPU_NAME="nenhuma"
if command -v nvidia-smi &>/dev/null; then
    HAS_NVIDIA=true
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "NVIDIA")
elif lspci 2>/dev/null | grep -qi nvidia; then
    HAS_NVIDIA=true
    GPU_NAME="NVIDIA (driver nao instalado)"
fi

if [ "$NO_GPU" = true ]; then
    HAS_NVIDIA=false
    GPU_NAME="desabilitada (--no-gpu)"
fi

# Calcular MAX_CHROME pela RAM
if [ "$TOTAL_RAM_GB" -ge 200 ]; then
    MAX_CHROME=50
elif [ "$TOTAL_RAM_GB" -ge 100 ]; then
    MAX_CHROME=25
elif [ "$TOTAL_RAM_GB" -ge 50 ]; then
    MAX_CHROME=12
elif [ "$TOTAL_RAM_GB" -ge 20 ]; then
    MAX_CHROME=8
elif [ "$TOTAL_RAM_GB" -ge 8 ]; then
    MAX_CHROME=4
else
    MAX_CHROME=2
fi

echo "  RAM:  ${TOTAL_RAM_GB}GB"
echo "  CPU:  ${CPU_CORES} cores"
echo "  GPU:  ${GPU_NAME}"
echo "  Chrome maximo: ${MAX_CHROME}"
echo ""

# ─── Instalar Docker ─────────────────────────────────────
echo "[2/7] Docker..."

if ! command -v docker &>/dev/null; then
    echo "  Instalando Docker..."
    curl -fsSL https://get.docker.com | bash
    systemctl enable docker
    systemctl start docker
    echo "  Docker instalado"
else
    echo "  Docker OK: $(docker --version | cut -d' ' -f3)"
fi

# Docker Compose (plugin)
if ! docker compose version &>/dev/null; then
    echo "  Instalando Docker Compose plugin..."
    apt-get update -qq && apt-get install -y -qq docker-compose-plugin
fi
echo "  Compose: $(docker compose version --short 2>/dev/null || echo 'OK')"

# ─── NVIDIA Container Toolkit ────────────────────────────
echo ""
echo "[3/7] GPU..."

if [ "$HAS_NVIDIA" = true ]; then
    # Instalar driver se necessario
    if ! command -v nvidia-smi &>/dev/null; then
        echo "  Instalando NVIDIA driver..."
        apt-get update -qq
        apt-get install -y -qq nvidia-driver-535 2>/dev/null || \
        apt-get install -y -qq nvidia-driver-530 2>/dev/null || \
        apt-get install -y -qq nvidia-driver-525 2>/dev/null || \
        echo "  AVISO: nao consegui instalar driver automaticamente"
        echo "  Instale manualmente: apt install nvidia-driver-535"
    fi

    # Container toolkit
    if ! dpkg -l 2>/dev/null | grep -q nvidia-container-toolkit; then
        echo "  Instalando NVIDIA Container Toolkit..."
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
            gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null
        distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
        curl -s -L "https://nvidia.github.io/libnvidia-container/${distribution}/libnvidia-container.list" | \
            sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
            tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
        apt-get update -qq && apt-get install -y -qq nvidia-container-toolkit
        nvidia-ctk runtime configure --runtime=docker
        systemctl restart docker
        echo "  NVIDIA Toolkit instalado"
    else
        echo "  NVIDIA Toolkit OK"
    fi

    # Verificar GPU no Docker
    if docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi &>/dev/null; then
        echo "  GPU no Docker: OK"
    else
        echo "  AVISO: GPU nao detectada no Docker. Pode precisar reboot."
    fi
else
    echo "  Sem GPU NVIDIA, usando modo CPU"
fi

# ─── Clonar projeto ──────────────────────────────────────
echo ""
echo "[4/7] Projeto..."

if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  Atualizando $INSTALL_DIR..."
    cd "$INSTALL_DIR"
    git pull origin main 2>/dev/null || true
else
    echo "  Clonando em $INSTALL_DIR..."
    git clone "$REPO" "$INSTALL_DIR" 2>/dev/null
    cd "$INSTALL_DIR"
fi
echo "  Projeto em: $INSTALL_DIR"

# ─── Configurar .env ─────────────────────────────────────
echo ""
echo "[5/7] Configuracao..."

# Pedir Redis URL se nao fornecido
if [ -z "$REDIS_URL" ]; then
    if [ -f .env ]; then
        REDIS_URL=$(grep REDIS_URL .env 2>/dev/null | cut -d= -f2-)
    fi
    if [ -z "$REDIS_URL" ]; then
        echo ""
        echo "  REDIS_URL nao configurado!"
        echo "  Informe a URL do Redis (ou edite .env depois):"
        read -p "  REDIS_URL: " REDIS_URL
    fi
fi

cat > .env << EOF
REDIS_URL=${REDIS_URL}
MAX_CHROME=${MAX_CHROME}
WORKER_ID=worker-${HOSTNAME_SHORT}
API_PORT=8000
EOF

echo "  .env criado:"
echo "    REDIS_URL=${REDIS_URL:0:40}..."
echo "    MAX_CHROME=${MAX_CHROME}"
echo "    WORKER_ID=worker-${HOSTNAME_SHORT}"

# ─── VPN (opcional) ──────────────────────────────────────
echo ""
echo "[6/7] VPN..."

if [ -n "$VPN_CONF" ] && [ -f "$VPN_CONF" ]; then
    mkdir -p docker/vpn
    cp "$VPN_CONF" docker/vpn/
    echo "  VPN config copiada: $(basename $VPN_CONF)"
elif [ -d docker/vpn ] && ls docker/vpn/*.conf &>/dev/null; then
    echo "  VPN configs encontradas em docker/vpn/"
else
    echo "  Sem VPN configurada (pode adicionar depois em docker/vpn/)"
fi

# ─── Build e Start ────────────────────────────────────────
echo ""
echo "[7/7] Build e start..."

if [ "$HAS_NVIDIA" = true ]; then
    WORKER_SERVICE="worker-gpu"
    echo "  Buildando worker-gpu..."
    docker compose build worker-gpu 2>&1 | tail -3
else
    WORKER_SERVICE="worker-nogpu"
    echo "  Buildando worker-nogpu..."
    docker compose --profile nogpu build worker-nogpu 2>&1 | tail -3
fi

if [ "$RUN_API" = true ]; then
    echo "  Buildando api..."
    docker compose build api 2>&1 | tail -3
    echo "  Subindo api + ${WORKER_SERVICE}..."
    if [ "$HAS_NVIDIA" = true ]; then
        docker compose up -d api worker-gpu
    else
        docker compose up -d api
        docker compose --profile nogpu up -d worker-nogpu
    fi
else
    echo "  Subindo ${WORKER_SERVICE}..."
    if [ "$HAS_NVIDIA" = true ]; then
        docker compose up -d worker-gpu
    else
        docker compose --profile nogpu up -d worker-nogpu
    fi
fi

# ─── Verificacao ──────────────────────────────────────────
echo ""
sleep 5

echo "╔══════════════════════════════════════════════════════╗"
echo "║  Setup Concluido!                                    ║"
echo "╠══════════════════════════════════════════════════════╣"

# Status dos containers
docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null | while read line; do
    echo "║  $line"
done

echo "╠══════════════════════════════════════════════════════╣"
echo "║  Maquina: $(hostname)"
echo "║  RAM: ${TOTAL_RAM_GB}GB | CPU: ${CPU_CORES} cores | GPU: ${GPU_NAME}"
echo "║  Chrome: max ${MAX_CHROME} simultaneos"
echo "║  Worker: worker-${HOSTNAME_SHORT}"

if [ "$RUN_API" = true ]; then
    IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    echo "║"
    echo "║  API:       http://${IP}:8000"
    echo "║  Dashboard: http://${IP}:8000/dashboard"
fi

echo "╠══════════════════════════════════════════════════════╣"
echo "║  Comandos:"
echo "║    docker compose logs -f           # ver logs"
echo "║    docker compose ps                # status"
echo "║    docker compose restart           # reiniciar"
echo "║    docker compose down              # parar"
echo "║    cd $INSTALL_DIR && git pull      # atualizar"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ─── Criar servico systemd (auto-start no boot) ──────────
cat > /etc/systemd/system/pedro-worker.service << EOF
[Unit]
Description=PEDRO Certidoes Worker
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable pedro-worker.service 2>/dev/null
echo "Servico systemd criado: pedro-worker (auto-start no boot)"
echo ""

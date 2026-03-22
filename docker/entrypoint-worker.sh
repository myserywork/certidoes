#!/bin/bash
set -e

export DOCKER=1
MAX_CHROME=${MAX_CHROME:-6}
WORKER_ID=${WORKER_ID:-"worker-$(hostname | cut -c1-8)"}

# ─── Xvfb ─────────────────────────────────────────────────
echo "[setup] Xvfb :99..."
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX &>/dev/null &
sleep 1

# ─── VPN (opcional) ───────────────────────────────────────
if [ -d /etc/wireguard ] && ls /etc/wireguard/wg*.conf &>/dev/null; then
    for conf in /etc/wireguard/wg*.conf; do
        iface=$(basename "$conf" .conf)
        echo "[vpn] Subindo $iface..."
        wg-quick up "$iface" 2>/dev/null || echo "[vpn] AVISO: $iface falhou"
    done
    VPN_IP=$(curl -s --max-time 5 https://ifconfig.me 2>/dev/null || echo "?")
    echo "[vpn] IP externo: $VPN_IP"
else
    echo "[vpn] Sem configs WireGuard, rodando sem VPN"
fi

# ─── Cleanup Chrome locks ────────────────────────────────
rm -f /tmp/.org.chromium.Chromium.* 2>/dev/null
rm -f /tmp/chrome_profile/SingletonLock 2>/dev/null

# ─── Chrome config para container ─────────────────────────
# Desabilitar sandbox (roda como root no container)
export CHROME_FLAGS="--no-sandbox --disable-dev-shm-usage --disable-gpu"

# Garantir que chromedriver existe e ta no PATH
if ! command -v chromedriver &>/dev/null; then
    CHROME_VERSION=$(google-chrome --version | grep -oP '\d+\.\d+\.\d+')
    CHROME_MAJOR=$(echo $CHROME_VERSION | cut -d. -f1)
    echo "[setup] Baixando chromedriver para Chrome $CHROME_MAJOR..."
    # undetected_chromedriver baixa automaticamente, so precisa do Chrome
fi

echo "=========================================="
echo "  PEDRO Worker"
echo "  ID:     $WORKER_ID"
echo "  Chrome: $MAX_CHROME"
echo "  GPU:    $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null || echo 'nenhuma')"
echo "  Redis:  ${REDIS_URL:0:40}..."
echo "=========================================="

exec python3 -m api.worker --max-chrome "$MAX_CHROME" --id "$WORKER_ID"

#!/bin/bash
# Entrypoint do worker com VPN WireGuard
set -e

MAX_CHROME=${MAX_CHROME:-6}
WORKER_ID=${WORKER_ID:-"worker-vpn-$(hostname | cut -c1-8)"}

# Subir WireGuard
if [ -f /etc/wireguard/wg0.conf ]; then
    echo "[vpn] Subindo WireGuard..."
    wg-quick up wg0
    VPN_IP=$(curl -s --max-time 10 https://ifconfig.me 2>/dev/null || echo "?")
    echo "[vpn] IP: $VPN_IP"
else
    echo "[vpn] AVISO: /etc/wireguard/wg0.conf nao encontrado, rodando sem VPN"
fi

# Xvfb
echo "[entrypoint] Iniciando Xvfb :99..."
Xvfb :99 -screen 0 1920x1080x24 -ac &
sleep 1

echo "[entrypoint] Worker: $WORKER_ID | Chrome: $MAX_CHROME"
exec python3 -m api.worker --max-chrome "$MAX_CHROME" --id "$WORKER_ID"

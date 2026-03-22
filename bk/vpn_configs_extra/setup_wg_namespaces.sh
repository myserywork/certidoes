#!/bin/bash
# Setup WireGuard namespaces para PEDRO PROJECT
set -e

KEYS_DIR="/root/mullvad_wg/keys"

echo "=== Criando Network Namespaces ==="
for i in 0 1 2 3 4; do
    NS="ns_t${i}"
    ip netns list 2>/dev/null | grep -q "${NS}" || ip netns add "${NS}"
    ip netns exec "${NS}" ip link set lo up 2>/dev/null || true
    echo "  ${NS}: OK"
done

echo ""
echo "=== Configurando WireGuard ==="
for i in 0 1 2 3 4; do
    NS="ns_t${i}"
    WG_IF="wg_t${i}"
    CONF="${KEYS_DIR}/wg_t${i}.conf"

    echo "  Configurando ${NS}/${WG_IF}..."

    # Limpar
    ip link del "${WG_IF}" 2>/dev/null || true
    ip netns exec "${NS}" ip link del "${WG_IF}" 2>/dev/null || true

    # Criar interface WireGuard
    ip link add "${WG_IF}" type wireguard

    # Extrair dados do conf
    PRIVKEY=$(grep "PrivateKey" "${CONF}" | cut -d'=' -f2- | tr -d ' ')
    ADDRESS=$(grep "Address" "${CONF}" | cut -d'=' -f2- | tr -d ' ')
    PUBKEY=$(grep "PublicKey" "${CONF}" | cut -d'=' -f2- | tr -d ' ')
    ENDPOINT=$(grep "Endpoint" "${CONF}" | cut -d'=' -f2- | tr -d ' ')

    # Mover para namespace
    ip link set "${WG_IF}" netns "${NS}"

    # Configurar WireGuard
    TMPKEY=$(mktemp)
    echo "${PRIVKEY}" > "${TMPKEY}"
    ip netns exec "${NS}" wg set "${WG_IF}" \
        private-key "${TMPKEY}" \
        peer "${PUBKEY}" \
        endpoint "${ENDPOINT}" \
        allowed-ips "0.0.0.0/0"
    rm -f "${TMPKEY}"

    # Atribuir IP e ativar
    ip netns exec "${NS}" ip addr add "${ADDRESS}" dev "${WG_IF}"
    ip netns exec "${NS}" ip link set "${WG_IF}" up
    ip netns exec "${NS}" ip route add default dev "${WG_IF}"

    echo "    UP -> ${ENDPOINT}"
done

echo ""
echo "=== Testando conectividade (10s timeout cada) ==="
for i in 0 1 2 3 4; do
    NS="ns_t${i}"
    IP=$(ip netns exec "${NS}" curl -s --max-time 10 https://ifconfig.me 2>/dev/null || echo "TIMEOUT")
    echo "  ${NS}: ${IP}"
done

echo ""
echo "=== DONE ==="

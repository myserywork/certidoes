#!/bin/bash
# ============================================================
# PEDRO PROJECT — VPN Setup para WSL2
#
# Arquitetura:
#   Default NS: wg_t0..wg_t4 (WireGuard interfaces com rota para Mullvad)
#   ns_t0..ns_t4: conectados via veth pairs, NAT para cada WG interface
#
#   ns_t0 --[veth]--> default NS --[wg_t0]--> Mullvad SP 1
#   ns_t1 --[veth]--> default NS --[wg_t1]--> Mullvad SP 2
#   ...
# ============================================================

set -e

KEYS_DIR="/root/mullvad_wg/keys"

echo "=== [1] Limpando estado anterior ==="
for i in 0 1 2 3 4; do
    wg-quick down "wg_t${i}" 2>/dev/null || true
    ip link del "veth_t${i}" 2>/dev/null || true
    ip netns del "ns_t${i}" 2>/dev/null || true
done
sleep 1

echo "=== [2] Subindo interfaces WireGuard (namespace default) ==="
for i in 0 1 2 3 4; do
    CONF="${KEYS_DIR}/wg_t${i}.conf"

    # Criar conf em /etc/wireguard com Table customizada (evita conflito de rotas)
    TNUM=$((51820 + i))

    cat > "/etc/wireguard/wg_t${i}.conf" << EOF
[Interface]
PrivateKey = $(grep "PrivateKey" "${CONF}" | sed 's/.*= //')
Address = $(grep "Address" "${CONF}" | sed 's/.*= //')
Table = ${TNUM}
PostUp = ip rule add fwmark ${TNUM} table ${TNUM}
PreDown = ip rule del fwmark ${TNUM} table ${TNUM} 2>/dev/null || true

[Peer]
PublicKey = $(grep "PublicKey" "${CONF}" | sed 's/.*= //')
AllowedIPs = 0.0.0.0/0
Endpoint = $(grep "Endpoint" "${CONF}" | sed 's/.*= //')
EOF

    wg-quick up "wg_t${i}" 2>&1 | grep -v "^$"
    echo "  wg_t${i}: UP (table ${TNUM})"
done

echo ""
echo "=== [3] Criando namespaces + veth pairs ==="
for i in 0 1 2 3 4; do
    NS="ns_t${i}"
    VETH_HOST="veth_t${i}"
    VETH_NS="veth_ns${i}"
    SUBNET="10.200.${i}"
    TNUM=$((51820 + i))

    # Criar namespace
    ip netns add "${NS}"
    ip netns exec "${NS}" ip link set lo up

    # Criar veth pair
    ip link add "${VETH_HOST}" type veth peer name "${VETH_NS}"

    # Mover um lado para o namespace
    ip link set "${VETH_NS}" netns "${NS}"

    # Configurar lado host
    ip addr add "${SUBNET}.1/24" dev "${VETH_HOST}"
    ip link set "${VETH_HOST}" up

    # Configurar lado namespace
    ip netns exec "${NS}" ip addr add "${SUBNET}.2/24" dev "${VETH_NS}"
    ip netns exec "${NS}" ip link set "${VETH_NS}" up
    ip netns exec "${NS}" ip route add default via "${SUBNET}.1"

    # DNS dentro do namespace
    mkdir -p "/etc/netns/${NS}"
    echo "nameserver 10.64.0.1" > "/etc/netns/${NS}/resolv.conf"

    # Marcar pacotes vindos deste namespace com fwmark para rotear pelo WG correto
    iptables -t nat -A POSTROUTING -s "${SUBNET}.0/24" -o "wg_t${i}" -j MASQUERADE
    iptables -t mangle -A PREROUTING -s "${SUBNET}.0/24" -j MARK --set-mark "${TNUM}"

    # Rota: pacotes com fwmark vão pela tabela do WG correspondente
    ip rule add fwmark "${TNUM}" table "${TNUM}" priority $((100 + i)) 2>/dev/null || true

    # MTU: veth deve ser <= WG MTU (1200) para evitar fragmentação
    ip link set "${VETH_HOST}" mtu 1200
    ip netns exec "${NS}" ip link set "${VETH_NS}" mtu 1200

    echo "  ${NS}: ${SUBNET}.2 -> veth -> wg_t${i} -> Mullvad"
done

# Habilitar forwarding
sysctl -w net.ipv4.ip_forward=1 > /dev/null

# TCP MSS clamp (evita problemas com MTU em conexoes TCP/TLS)
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

echo ""
echo "=== [4] Testando conectividade de cada namespace ==="
for i in 0 1 2 3 4; do
    NS="ns_t${i}"
    IP=$(ip netns exec "${NS}" curl -s --max-time 15 https://ifconfig.me 2>/dev/null || echo "TIMEOUT")
    echo "  ${NS}: ${IP}"
done

echo ""
echo "=== DONE ==="

#!/bin/bash
# ============================================================
# Mullvad VPN — Setup de Network Namespaces para PEDRO PROJECT
# Cria 5 namespaces (ns_t0 a ns_t4) com interfaces WireGuard
# ============================================================
#
# PRE-REQUISITOS:
# 1. Conta Mullvad ativa (https://mullvad.net)
# 2. Gerar configs WireGuard no painel Mullvad:
#    - Acesse https://mullvad.net/en/account/wireguard-config
#    - Gere 5 configs (uma para cada namespace)
#    - Salve como: /root/mullvad_wg/keys/wg_t0.conf ... wg_t4.conf
#
# FORMATO do arquivo .conf (exemplo wg_t0.conf):
# [Interface]
# PrivateKey = SUA_CHAVE_PRIVADA_AQUI
# Address = 10.68.xxx.xxx/32
# DNS = 100.64.0.2
#
# [Peer]
# PublicKey = CHAVE_PUBLICA_SERVIDOR
# AllowedIPs = 0.0.0.0/0
# Endpoint = xxx.xxx.xxx.xxx:51820
# ============================================================

set -e

KEYS_DIR="/root/mullvad_wg/keys"

echo "=== Verificando configs WireGuard ==="
MISSING=0
for i in 0 1 2 3 4; do
    CONF="${KEYS_DIR}/wg_t${i}.conf"
    if [ ! -f "${CONF}" ]; then
        echo "  FALTA: ${CONF}"
        MISSING=$((MISSING + 1))
    else
        echo "  OK: ${CONF}"
    fi
done

if [ ${MISSING} -gt 0 ]; then
    echo ""
    echo "================================================"
    echo "  ACAO NECESSARIA: Gere ${MISSING} configs WireGuard no Mullvad"
    echo "  https://mullvad.net/en/account/wireguard-config"
    echo "  Salve em: ${KEYS_DIR}/wg_t0.conf ... wg_t4.conf"
    echo "================================================"
    echo ""
    echo "Criando configs de EXEMPLO para voce preencher..."
    for i in 0 1 2 3 4; do
        CONF="${KEYS_DIR}/wg_t${i}.conf"
        if [ ! -f "${CONF}" ]; then
            cat > "${CONF}" << EOF
[Interface]
PrivateKey = COLE_SUA_CHAVE_PRIVADA_AQUI
Address = 10.68.0.${i}/32

[Peer]
PublicKey = COLE_CHAVE_PUBLICA_SERVIDOR_AQUI
AllowedIPs = 0.0.0.0/0
Endpoint = COLE_IP_SERVIDOR:51820
EOF
            echo "  Criado exemplo: ${CONF} (EDITE com suas chaves!)"
        fi
    done
    exit 1
fi

echo ""
echo "=== Criando Network Namespaces ==="
for i in 0 1 2 3 4; do
    NS="ns_t${i}"
    if ip netns list | grep -q "${NS}"; then
        echo "  ${NS} ja existe"
    else
        ip netns add "${NS}"
        echo "  Criado: ${NS}"
    fi
    ip netns exec "${NS}" ip link set lo up 2>/dev/null || true
done

echo ""
echo "=== Configurando interfaces WireGuard nos namespaces ==="
for i in 0 1 2 3 4; do
    NS="ns_t${i}"
    WG_IF="wg_t${i}"
    CONF="${KEYS_DIR}/wg_t${i}.conf"

    echo "  Configurando ${NS} com ${WG_IF}..."

    # Remover interface existente se houver
    ip link del "${WG_IF}" 2>/dev/null || true
    ip netns exec "${NS}" ip link del "${WG_IF}" 2>/dev/null || true

    # Criar interface WG
    ip link add "${WG_IF}" type wireguard

    # Extrair dados do conf
    PRIVKEY=$(grep "PrivateKey" "${CONF}" | awk '{print $3}')
    ADDRESS=$(grep "Address" "${CONF}" | awk '{print $3}')
    PUBKEY=$(grep "PublicKey" "${CONF}" | awk '{print $3}')
    ENDPOINT=$(grep "Endpoint" "${CONF}" | awk '{print $3}')

    # Mover interface para o namespace
    ip link set "${WG_IF}" netns "${NS}"

    # Configurar WireGuard dentro do namespace
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

    # Testar conectividade
    IP=$(ip netns exec "${NS}" curl -s --max-time 5 https://ifconfig.me 2>/dev/null || echo "TIMEOUT")
    echo "  ${NS} -> IP: ${IP}"
done

echo ""
echo "=== Status Final ==="
for i in 0 1 2 3 4; do
    NS="ns_t${i}"
    IP=$(ip netns exec "${NS}" curl -s --max-time 5 https://ifconfig.me 2>/dev/null || echo "OFFLINE")
    echo "  ${NS}: ${IP}"
done

echo ""
echo "============================================"
echo "  VPN Namespaces configurados!"
echo "  Use: ip netns exec ns_t0 curl https://httpbin.org/ip"
echo "============================================"

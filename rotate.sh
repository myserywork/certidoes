#!/bin/bash
# ============================================================
# rotate.sh — Rotaciona servidor WireGuard de um namespace
# Uso: ./rotate.sh rotate ns_t0 [br]
#      ./rotate.sh status
# ============================================================

KEYS_DIR="/root/mullvad_wg/keys"
POOL_FILE="/root/mullvad_wg/server_pool_full.json"

case "$1" in
    status)
        echo "=== Status dos Namespaces ==="
        for i in 0 1 2 3 4; do
            NS="ns_t${i}"
            IP=$(ip netns exec "${NS}" curl -s --max-time 5 https://ifconfig.me 2>/dev/null || echo "OFFLINE")
            echo "  ${NS}: ${IP}"
        done
        ;;
    rotate)
        NS="${2:-ns_t0}"
        FILTER="${3:-}"
        echo "Rotacionando ${NS}..."

        # Extrair indice do namespace
        IDX=$(echo "${NS}" | grep -o '[0-9]')
        WG_IF="wg_t${IDX}"
        CONF="${KEYS_DIR}/wg_t${IDX}.conf"

        if [ ! -f "${CONF}" ]; then
            echo "ERRO: ${CONF} nao encontrado"
            exit 1
        fi

        # Se tiver pool de servidores, escolher um aleatorio
        if [ -f "${POOL_FILE}" ] && command -v jq &>/dev/null; then
            if [ -n "${FILTER}" ]; then
                SERVER=$(jq -r "[.[] | select(.country == \"${FILTER}\")] | .[length * ($RANDOM / 32768) | floor]" "${POOL_FILE}" 2>/dev/null)
            else
                SERVER=$(jq -r ".[length * ($RANDOM / 32768) | floor]" "${POOL_FILE}" 2>/dev/null)
            fi
            if [ -n "${SERVER}" ] && [ "${SERVER}" != "null" ]; then
                NEW_PUBKEY=$(echo "${SERVER}" | jq -r '.public_key')
                NEW_ENDPOINT=$(echo "${SERVER}" | jq -r '.endpoint')
                if [ -n "${NEW_PUBKEY}" ] && [ "${NEW_PUBKEY}" != "null" ]; then
                    ip netns exec "${NS}" wg set "${WG_IF}" \
                        peer "${NEW_PUBKEY}" \
                        endpoint "${NEW_ENDPOINT}" \
                        allowed-ips "0.0.0.0/0" 2>/dev/null
                    echo "OK: ${NS} rotacionado para ${NEW_ENDPOINT}"
                    exit 0
                fi
            fi
        fi

        # Fallback: reiniciar interface com config original
        PUBKEY=$(grep "PublicKey" "${CONF}" | awk '{print $3}')
        ENDPOINT=$(grep "Endpoint" "${CONF}" | awk '{print $3}')
        ip netns exec "${NS}" wg set "${WG_IF}" \
            peer "${PUBKEY}" \
            endpoint "${ENDPOINT}" \
            allowed-ips "0.0.0.0/0" 2>/dev/null
        echo "OK: ${NS} reiniciado com config original"
        ;;
    *)
        echo "Uso: $0 {status|rotate <ns> [country_filter]}"
        ;;
esac

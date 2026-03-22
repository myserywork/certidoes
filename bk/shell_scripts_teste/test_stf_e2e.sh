#!/bin/bash
# Test STF end-to-end with local AWS WAF solver
export DISPLAY=:121
export HOME=/home/ramza
export NODE_PATH=/home/ramza/node_modules
export CAPTCHA_DISPLAY=:121

LOG="/home/ramza/telegram_downloads/PEDRO_PROJECT/test_results/stf_e2e_log.txt"
mkdir -p "$(dirname "$LOG")"

echo "=== STF End-to-End Test ===" > "$LOG"
echo "Started: $(date)" >> "$LOG"

cd /home/ramza/telegram_downloads/PEDRO_PROJECT

# Kill orphan chrome first
for pid in $(ps aux | grep chrome | grep -v grep | grep -v profiles_v15 | awk '{print $2}'); do kill -9 $pid 2>/dev/null; done

# Test with a public CNPJ
python3 14-certidao_STF.py --cpf "00000000000" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "Finished: $(date)" >> "$LOG"
echo "DONE" >> "$LOG"

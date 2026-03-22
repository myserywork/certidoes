#!/bin/bash
# Test TCU end-to-end with local reCAPTCHA solver
export DISPLAY=:121
export HOME=/home/ramza
export NODE_PATH=/home/ramza/node_modules
export CAPTCHA_DISPLAY=:121

LOG="/home/ramza/telegram_downloads/PEDRO_PROJECT/test_results/tcu_e2e_log.txt"
mkdir -p "$(dirname "$LOG")"

echo "=== TCU End-to-End Test ===" > "$LOG"
echo "Started: $(date)" >> "$LOG"

cd /home/ramza/telegram_downloads/PEDRO_PROJECT

# Test with a known public CNPJ (TCU itself: 00.414.607/0001-18)
python3 11-certidao_TCU.py --cnpj "00414607000118" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "Finished: $(date)" >> "$LOG"
echo "DONE" >> "$LOG"

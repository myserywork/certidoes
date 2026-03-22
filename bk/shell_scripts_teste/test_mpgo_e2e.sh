#!/bin/bash
export DISPLAY=:121
export HOME=/home/ramza
export NODE_PATH=/home/ramza/node_modules
export CAPTCHA_DISPLAY=:121

LOG="/home/ramza/telegram_downloads/PEDRO_PROJECT/test_results/mpgo_e2e_log.txt"
mkdir -p "$(dirname "$LOG")"

# Kill orphan chrome
for pid in $(ps aux | grep chrome | grep -v grep | grep -v profiles_v15 | awk '{print $2}'); do kill -9 $pid 2>/dev/null; done

echo "=== MPGO End-to-End Test ===" > "$LOG"
echo "Started: $(date)" >> "$LOG"

cd /home/ramza/telegram_downloads/PEDRO_PROJECT

python3 18-certidao_MPGO.py --cnpj "33000167000101" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "Finished: $(date)" >> "$LOG"
echo "DONE" >> "$LOG"

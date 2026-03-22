#!/bin/bash
# Test IBAMA full flow: Enterprise reCAPTCHA + certidão emission
export DISPLAY=:121
export NODE_PATH=/home/ramza/node_modules
export HOME=/home/ramza
cd /home/ramza

pkill -9 -f "profiles/ibama" 2>/dev/null
sleep 0.5

OUTDIR="/home/ramza/telegram_downloads/PEDRO_PROJECT/test_results"
mkdir -p "$OUTDIR"

# Use a test CPF
timeout 90 python3 /home/ramza/telegram_downloads/PEDRO_PROJECT/16-certidao_IBAMA.py \
  --cpf "12345678909" \
  > "$OUTDIR/ibama_full_result.json" 2> "$OUTDIR/ibama_full_log.txt"

RC=$?
echo "exit:$RC" >> "$OUTDIR/ibama_full_log.txt"

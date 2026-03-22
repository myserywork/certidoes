#!/bin/bash
export DISPLAY=:120
cd /home/ramza
pkill -9 -f "profiles/tcu" 2>/dev/null
sleep 0.5
OUTDIR="/home/ramza/telegram_downloads/PEDRO_PROJECT/test_results"
mkdir -p "$OUTDIR"
timeout 80 python3 /home/ramza/telegram_downloads/PEDRO_PROJECT/infra/local_captcha_solver.py \
  "https://contas.tcu.gov.br/certidao/Web/Certidao/NadaConsta/home.faces" \
  --profile tcu --display :120 \
  > "$OUTDIR/tcu_token.txt" 2> "$OUTDIR/tcu_log.txt"
echo "exit:$?" >> "$OUTDIR/tcu_log.txt"

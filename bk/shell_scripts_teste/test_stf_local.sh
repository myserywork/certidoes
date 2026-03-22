#!/bin/bash
export DISPLAY=:121
export NODE_PATH=/home/ramza/node_modules
export HOME=/home/ramza
cd /home/ramza

OUTDIR="/home/ramza/telegram_downloads/PEDRO_PROJECT/test_results"
mkdir -p "$OUTDIR"

timeout 90 python3 /home/ramza/telegram_downloads/PEDRO_PROJECT/infra/aws_waf_solver.py \
  "https://certidoes.stf.jus.br/" \
  --display :121 \
  > "$OUTDIR/stf_token.txt" 2> "$OUTDIR/stf_log.txt"

RC=$?
echo "exit:$RC" >> "$OUTDIR/stf_log.txt"

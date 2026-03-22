#!/bin/bash
# Test IBAMA reCAPTCHA solver with postNav (navigate to certidão module first)
export DISPLAY=:121
cd /home/ramza
pkill -9 -f "profiles/ibama" 2>/dev/null
sleep 0.5
OUTDIR="/home/ramza/telegram_downloads/PEDRO_PROJECT/test_results"
mkdir -p "$OUTDIR"

# PostNav JS: submit form to navigate to certidão module where reCAPTCHA appears
POST_NAV_JS="document.querySelector('input[name=\"modulo\"]').value='sisarr/cons_emitir_certidao'; document.forms['menuweb_submit'].submit();"

timeout 120 python3 /home/ramza/telegram_downloads/PEDRO_PROJECT/infra/local_captcha_solver.py \
  "https://servicos.ibama.gov.br/sicafiext/sistema.php" \
  --profile ibama --display :121 \
  --post-nav-js "$POST_NAV_JS" \
  > "$OUTDIR/ibama_token.txt" 2> "$OUTDIR/ibama_log.txt"

RC=$?
echo "exit:$RC" >> "$OUTDIR/ibama_log.txt"
echo "=== RESULTADO ===" >> "$OUTDIR/ibama_log.txt"
if [ $RC -eq 0 ]; then
    echo "SUCESSO" >> "$OUTDIR/ibama_log.txt"
else
    echo "FALHOU (rc=$RC)" >> "$OUTDIR/ibama_log.txt"
fi

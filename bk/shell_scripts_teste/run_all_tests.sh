#!/bin/bash
# Teste end-to-end de todos os scripts de certidão
# CPF de teste: 13683315725 (THAINA SANTOS GONCALVES)
export DISPLAY=:120
DIR="/home/ramza/telegram_downloads/PEDRO_PROJECT"
cd "$DIR"
CPF="13683315725"
OUTDIR="$DIR/test_results"
mkdir -p "$OUTDIR"

log() { echo "[$(date +%H:%M:%S)] $1" | tee -a "$OUTDIR/summary.txt"; }

log "========================================"
log "TESTE END-TO-END — $(date)"
log "CPF: $CPF"
log "========================================"

# --- 15: TRT18 (sem captcha, mais rápido) ---
log ""
log ">>> 15-TRT18 (sem captcha, Selenium UC)"
timeout 90 python3 -c "
import sys, json
sys.path.insert(0, '$DIR')
from importlib.machinery import SourceFileLoader
mod = SourceFileLoader('trt18', '$DIR/15-certidao_TRT18.py').load_module()
bot = mod.Navegador(headless=True)
try:
    r = bot.emitir_certidao('$CPF', 'andamento')
    print(json.dumps(r or {'status':'sem_resultado'}, ensure_ascii=False, indent=2))
finally:
    bot.fechar()
" > "$OUTDIR/15_result.json" 2> "$OUTDIR/15_log.txt"
RC=$?
log "Exit: $RC"
cat "$OUTDIR/15_result.json" | head -10 >> "$OUTDIR/summary.txt"
log "---"

# --- 11: TCU (reCAPTCHA v2 + 2captcha) ---
log ""
log ">>> 11-TCU (reCAPTCHA v2 + 2captcha)"
timeout 180 python3 "$DIR/11-certidao_TCU.py" --cpf "$CPF" > "$OUTDIR/11_result.json" 2> "$OUTDIR/11_log.txt"
RC=$?
log "Exit: $RC"
cat "$OUTDIR/11_result.json" | head -10 >> "$OUTDIR/summary.txt"
log "---"

# --- 16: IBAMA (reCAPTCHA v2 + 2captcha) ---
log ""
log ">>> 16-IBAMA (reCAPTCHA v2 + 2captcha)"
timeout 180 python3 "$DIR/16-certidao_IBAMA.py" --cpf "$CPF" > "$OUTDIR/16_result.json" 2> "$OUTDIR/16_log.txt"
RC=$?
log "Exit: $RC"
cat "$OUTDIR/16_result.json" | head -10 >> "$OUTDIR/summary.txt"
log "---"

# --- 14: STF (AWS WAF + 2captcha) ---
log ""
log ">>> 14-STF (AWS WAF + 2captcha)"
timeout 180 python3 "$DIR/14-certidao_STF.py" --cpf "$CPF" > "$OUTDIR/14_result.json" 2> "$OUTDIR/14_log.txt"
RC=$?
log "Exit: $RC"
cat "$OUTDIR/14_result.json" | head -10 >> "$OUTDIR/summary.txt"
log "---"

# --- 12: CPF Receita (hCaptcha + 2captcha) — data nascimento chutada ---
log ""
log ">>> 12-CPF Receita (hCaptcha + 2captcha)"
log "NOTA: Data nascimento 01/01/1990 é chute — pode dar erro de dados"
timeout 180 python3 "$DIR/12-certidao_CPF_Receita.py" --cpf "$CPF" --nascimento "01/01/1990" > "$OUTDIR/12_result.json" 2> "$OUTDIR/12_log.txt"
RC=$?
log "Exit: $RC"
cat "$OUTDIR/12_result.json" | head -10 >> "$OUTDIR/summary.txt"
log "---"

log ""
log "========================================"
log "TESTES CONCLUÍDOS — $(date)"
log "========================================"

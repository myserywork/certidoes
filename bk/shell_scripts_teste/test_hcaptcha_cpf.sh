#!/bin/bash
# Test hCaptcha CLIP solver on CPF Receita
# Runs as background, outputs to log file

export DISPLAY=:121
export HOME=/home/ramza
export NODE_PATH=/home/ramza/node_modules
export CAPTCHA_DISPLAY=:121

LOG="/home/ramza/telegram_downloads/PEDRO_PROJECT/test_results/hcaptcha_cpf_log.txt"
mkdir -p "$(dirname "$LOG")"

echo "=== hCaptcha CPF Receita Test ===" > "$LOG"
echo "Started: $(date)" >> "$LOG"

cd /home/ramza/telegram_downloads/PEDRO_PROJECT

# First, test just the hcaptcha solver directly (not the full CPF script)
echo "--- Testing hcaptcha_solver.py directly ---" >> "$LOG"
python3 -c "
import sys
sys.path.insert(0, '.')
from infra.hcaptcha_solver import solve_hcaptcha

url = 'https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/consultapublica.asp'
token = solve_hcaptcha(url, display=':121')
if token:
    print(f'SUCCESS: token={len(token)} chars')
    print(f'TOKEN_START: {token[:100]}...')
else:
    print('FAILED: no token')
" >> "$LOG" 2>&1

echo "Finished: $(date)" >> "$LOG"
echo "DONE" >> "$LOG"

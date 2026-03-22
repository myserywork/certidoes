#!/bin/bash
# Test hCaptcha CLIP solver v2 on CPF Receita
export DISPLAY=:121
export HOME=/home/ramza
export NODE_PATH=/home/ramza/node_modules
export CAPTCHA_DISPLAY=:121

LOG="/home/ramza/telegram_downloads/PEDRO_PROJECT/test_results/hcaptcha_v2_log.txt"
mkdir -p "$(dirname "$LOG")"

echo "=== hCaptcha v2 Test ===" > "$LOG"
echo "Started: $(date)" >> "$LOG"

cd /home/ramza/telegram_downloads/PEDRO_PROJECT

python3 -c "
import sys
sys.path.insert(0, '.')
from infra.hcaptcha_solver import solve_hcaptcha

url = 'https://servicos.receita.fazenda.gov.br/servicos/cpf/consultasituacao/consultapublica.asp'
token = solve_hcaptcha(url, display=':121')
if token:
    print(f'SUCCESS: token={len(token)} chars')
    print(f'TOKEN_START: {token[:100]}...')
    with open('test_results/hcaptcha_v2_token.txt', 'w') as f:
        f.write(token)
else:
    print('FAILED: no token')
" >> "$LOG" 2>&1

echo "Finished: $(date)" >> "$LOG"
echo "DONE" >> "$LOG"

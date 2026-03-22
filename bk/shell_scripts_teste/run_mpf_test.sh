#!/bin/bash
export DISPLAY=:120
cd /home/ramza
pkill -9 -f "profiles/mpf" 2>/dev/null
sleep 0.5
python3 /home/ramza/telegram_downloads/PEDRO_PROJECT/13-certidao_MPF.py --cpf 13683315725 \
  > /home/ramza/telegram_downloads/PEDRO_PROJECT/mpf_result.json \
  2> /home/ramza/telegram_downloads/PEDRO_PROJECT/mpf_test.log
echo "exit:$?" >> /home/ramza/telegram_downloads/PEDRO_PROJECT/mpf_test.log

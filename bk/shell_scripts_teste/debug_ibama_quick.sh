#!/bin/bash
export DISPLAY=:121
export NODE_PATH=/home/ramza/node_modules
export HOME=/home/ramza
cd /home/ramza

pkill -9 -f "profiles/ibama" 2>/dev/null
sleep 0.5

node /home/ramza/telegram_downloads/PEDRO_PROJECT/debug_ibama_selectors.js \
  > /home/ramza/telegram_downloads/PEDRO_PROJECT/test_results/ibama_debug.log 2>&1

echo "EXIT: $?" >> /home/ramza/telegram_downloads/PEDRO_PROJECT/test_results/ibama_debug.log

@echo off
REM ============================================================
REM PEDRO PROJECT — Setup Windows
REM
REM Requisitos: Python 3.10+, Node 18+, Chrome instalado
REM
REM Uso: setup_windows.bat
REM ============================================================

echo.
echo =============================================
echo   PEDRO PROJECT — Setup Windows
echo =============================================
echo.

REM ─── Verificar Python ─────────────────────────
python --version 2>nul
if %errorlevel% neq 0 (
    echo ERRO: Python nao encontrado. Instale Python 3.10+
    echo https://www.python.org/downloads/
    pause
    exit /b 1
)

REM ─── Verificar Node ───────────────────────────
node --version 2>nul
if %errorlevel% neq 0 (
    echo ERRO: Node.js nao encontrado. Instale Node 18+
    echo https://nodejs.org/
    pause
    exit /b 1
)

REM ─── Verificar Chrome ─────────────────────────
where chrome 2>nul >nul || where "C:\Program Files\Google\Chrome\Application\chrome.exe" 2>nul >nul
echo Chrome: OK

REM ─── Instalar deps Python ─────────────────────
echo.
echo [1/4] Instalando dependencias Python...
pip install fastapi uvicorn pydantic redis requests flask ^
    openai-whisper torch torchaudio transformers Pillow ^
    undetected-chromedriver selenium

REM ─── Instalar deps Node ───────────────────────
echo.
echo [2/4] Instalando dependencias Node.js...
if not exist node_modules (
    npm install puppeteer-extra puppeteer-extra-plugin-stealth puppeteer
)

REM ─── Criar .env se nao existe ─────────────────
echo.
echo [3/4] Configuracao...
if not exist .env (
    copy .env.example .env
    echo .env criado. EDITE com sua REDIS_URL e CAPTCHA_API_KEY
) else (
    echo .env ja existe
)

REM ─── Criar pastas ─────────────────────────────
if not exist logs mkdir logs
if not exist api\downloads mkdir api\downloads

echo.
echo [4/4] Pronto!
echo.
echo =============================================
echo   Para iniciar:
echo.
echo   API:    python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
echo   Worker: python -m api.worker --max-chrome 6
echo   Ambos:  start_windows.bat
echo.
echo   Dashboard: http://localhost:8000/dashboard
echo =============================================
echo.
pause

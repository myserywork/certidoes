@echo off
REM ============================================================
REM PEDRO PROJECT — Iniciar API + Worker no Windows
REM ============================================================

echo.
echo =============================================
echo   PEDRO PROJECT — Windows
echo =============================================
echo.

REM Iniciar API em background
echo Iniciando API na porta 8000...
start "PEDRO-API" /min cmd /c "python -m uvicorn api.main:app --host 0.0.0.0 --port 8000"

timeout /t 3 /nobreak >nul

REM Iniciar Worker
echo Iniciando Worker...
echo.
echo Dashboard: http://localhost:8000/dashboard
echo.
python -m api.worker --max-chrome 6 --id worker-windows

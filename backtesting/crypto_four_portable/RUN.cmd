@echo off
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: RUN.cmd "D:\Personal\OpenAlgo_Crypto\historical_data"
  exit /b 1
)
.venv\Scripts\python.exe -u crypto_backtest.py --data "%~1" --output results --workers 4
pause

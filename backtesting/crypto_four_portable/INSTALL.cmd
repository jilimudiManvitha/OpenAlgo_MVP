@echo off
cd /d "%~dp0"
py -3.13 -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m unittest -v test_crypto_backtest
if errorlevel 1 exit /b 1
echo Installation and synthetic tests complete. See README.md for run command.
pause

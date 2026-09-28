$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path (Split-Path $PSScriptRoot -Parent) '.venv/Scripts/python.exe'
& $pythonPath -u (Join-Path $PSScriptRoot 'run.py') @args
exit $LASTEXITCODE

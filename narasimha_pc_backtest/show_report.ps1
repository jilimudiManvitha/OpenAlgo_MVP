$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path (Split-Path $PSScriptRoot -Parent) '.venv/Scripts/python.exe'
& $pythonPath (Join-Path $PSScriptRoot 'serve.py') @args
exit $LASTEXITCODE

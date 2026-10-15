# One-command setup (Windows PowerShell 5.1, Python 3.9+)
$ErrorActionPreference = "Stop"
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env - fill in your values" }

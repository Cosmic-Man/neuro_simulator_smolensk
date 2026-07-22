$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    python -m venv .venv
}

& ".venv\Scripts\python.exe" -m pip install --upgrade pip
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "Создан .env из .env.example"
}

docker compose up -d postgres
& ".venv\Scripts\python.exe" -m alembic upgrade head
& ".venv\Scripts\python.exe" -m app.manage seed-demo-users

Write-Host "Окружение и PostgreSQL готовы. Запуск: .\run_local.ps1"


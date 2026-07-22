$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Python = if (Test-Path -LiteralPath ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $Python -m alembic upgrade head
& $Python -m app.manage seed-demo-users
& $Python -m uvicorn app.main:app --host 127.0.0.1 --port 8000


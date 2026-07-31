# Windows equivalent of scripts/dev_up.sh: start the whole studio and stop
# everything on Ctrl-C. Run scripts\setup.ps1 once first.
#
#   powershell -ExecutionPolicy Bypass -File scripts\start.ps1
#   $env:DEV_ENGINES = "0"; powershell -File scripts\start.ps1   # real engines (GPU host)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path .venv)) { Write-Host "Run scripts\setup.ps1 first." -ForegroundColor Red; exit 1 }
if (-not $env:DEV_ENGINES) { $env:DEV_ENGINES = "1" }

Write-Host "==> infrastructure (postgres, redis, minio)"
docker compose up -d --wait
if ($LASTEXITCODE -ne 0) { Write-Host "docker compose failed - start Docker Desktop" -ForegroundColor Red; exit 1 }

$py = Resolve-Path ".venv\Scripts\python.exe"
& $py -m alembic upgrade head
& $py -c "from pipeline_core.storage import ObjectStore; ObjectStore().ensure_bucket()"

$procs = @()
try {
  Write-Host "==> api :8000"
  $procs += Start-Process $py -ArgumentList "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000" -PassThru -NoNewWindow

  Write-Host "==> cpu worker (ffmpeg: preprocess, assemble, export, publish)"
  $procs += Start-Process $py -ArgumentList "worker_cpu/run.py" -PassThru -NoNewWindow

  Write-Host "==> render-lane worker (DEV_ENGINES=$env:DEV_ENGINES)"
  $procs += Start-Process $py -ArgumentList "worker_gpu/run.py" -PassThru -NoNewWindow

  Write-Host "==> wan-lane worker (generation queue)"
  $procs += Start-Process $py -ArgumentList "worker_gpu/run_wan.py" -PassThru -NoNewWindow

  Write-Host "==> panel :5173"
  $procs += Start-Process "npx" -ArgumentList "vite", "--port", "5173", "--strictPort" -WorkingDirectory "web" -PassThru -NoNewWindow

  Start-Sleep 3
  Write-Host ""
  Write-Host "  Studio:  http://localhost:5173" -ForegroundColor Cyan
  Write-Host "  API:     http://localhost:8000/docs"
  Write-Host "  MinIO:   http://localhost:9001  (minioadmin / minioadmin)"
  Write-Host ""
  Write-Host "  Ctrl-C stops everything."
  Wait-Process -Id ($procs | ForEach-Object Id)
} finally {
  Write-Host "==> stopping"
  foreach ($p in $procs) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
}

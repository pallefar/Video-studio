# One-command bootstrap for Windows 10/11: checks every dependency, installs
# what's missing via winget, prepares the stack. Idempotent — safe to re-run.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1          # install + prepare
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -Start   # ...then launch
#
# macOS / Linux: use scripts/setup.sh instead.
param([switch]$Start)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Ok($msg)   { Write-Host "  [ok] $msg" -ForegroundColor Green }
function Todo($msg) { Write-Host "  [->] $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  [x] $msg" -ForegroundColor Red; exit 1 }

Write-Host "== Video Studio setup (Windows) ==" -ForegroundColor Cyan

# --- winget ------------------------------------------------------------------
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
  Fail "winget missing - install 'App Installer' from the Microsoft Store, then re-run"
}

# --- git ---------------------------------------------------------------------
if (Get-Command git -ErrorAction SilentlyContinue) {
  Ok "git $((git --version) -replace 'git version ')"
} else {
  Todo "installing git"
  winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

# --- Python 3.11+ ------------------------------------------------------------
$py = $null
foreach ($candidate in @("python3.13", "python3.12", "python3.11", "python")) {
  $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
  if ($cmd) {
    $version = & $candidate -c "import sys; print('{}.{}'.format(*sys.version_info[:2]))" 2>$null
    if ($version -and [version]$version -ge [version]"3.11") { $py = $candidate; break }
  }
}
if ($py) {
  Ok "python $(& $py -c 'import sys; print(\".\".join(map(str, sys.version_info[:3])))') ($py)"
} else {
  Todo "installing Python 3.12"
  winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
  $py = "python"
}

# --- Node 20+ ----------------------------------------------------------------
$nodeOk = $false
if (Get-Command node -ErrorAction SilentlyContinue) {
  $major = [int]((node --version).TrimStart("v").Split(".")[0])
  if ($major -ge 20) { $nodeOk = $true; Ok "node $(node --version)" }
}
if (-not $nodeOk) {
  Todo "installing Node LTS"
  winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

# --- Docker Desktop ----------------------------------------------------------
$dockerReady = $false
if (Get-Command docker -ErrorAction SilentlyContinue) {
  docker info *> $null
  if ($LASTEXITCODE -eq 0) { $dockerReady = $true; Ok "docker running" }
}
if (-not $dockerReady) {
  if (Get-Command docker -ErrorAction SilentlyContinue) {
    Todo "starting Docker Desktop"
    Start-Process "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe" -ErrorAction SilentlyContinue
    foreach ($i in 1..60) {
      Start-Sleep 2
      docker info *> $null
      if ($LASTEXITCODE -eq 0) { $dockerReady = $true; break }
    }
    if ($dockerReady) { Ok "docker running" } else { Fail "Docker installed but not running - start Docker Desktop and re-run" }
  } else {
    Todo "installing Docker Desktop (requires WSL2; may need a reboot)"
    winget install --id Docker.DockerDesktop -e --accept-source-agreements --accept-package-agreements
    Fail "Docker Desktop installed - launch it once to finish its setup (enables WSL2), then re-run this script"
  }
}

# --- .env --------------------------------------------------------------------
if (Test-Path .env) { Ok ".env present" }
else { Todo "creating .env from .env.example"; Copy-Item .env.example .env }

# --- Python venv + package ---------------------------------------------------
if (-not (Test-Path .venv)) {
  Todo "creating virtualenv (.venv)"
  & $py -m venv .venv
}
Todo "installing python package (editable, [dev] extras)"
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\pip.exe install --quiet -e ".[dev]"
Ok "python deps"

# --- Web deps ----------------------------------------------------------------
if (-not (Test-Path web\node_modules)) {
  Todo "npm ci (web/)"
  Push-Location web; npm ci --silent; Pop-Location
}
Ok "web deps"

# --- Infrastructure + schema -------------------------------------------------
Todo "starting postgres / redis / minio"
docker compose up -d --wait
if ($LASTEXITCODE -ne 0) { Fail "docker compose failed - is Docker Desktop fully started?" }
Todo "migrations + bucket"
& .\.venv\Scripts\python.exe -m alembic upgrade head
& .\.venv\Scripts\python.exe -c "from pipeline_core.storage import ObjectStore; ObjectStore().ensure_bucket()"
Ok "database + object store ready"

Write-Host ""
Write-Host "Setup complete. Start the studio with:  powershell -File scripts\start.ps1" -ForegroundColor Cyan
Write-Host "  (DEV_ENGINES=1 placeholder engines by default; real engines need the GPU host - docs/workstation.md)"

if ($Start) { & powershell -ExecutionPolicy Bypass -File scripts\start.ps1 }

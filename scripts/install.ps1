# EOU Windows Installer (PowerShell)
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install.ps1

$ErrorActionPreference = "Stop"

# Force UTF-8 for Python stdout/stderr to avoid cp949 UnicodeEncodeError on Korean Windows
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "[EOU] Project root: $ProjectRoot" -ForegroundColor Cyan

# 1. Ensure uv is installed
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "[EOU] uv not found. Installing..." -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Error "uv install failed. Open a new terminal and re-run this script."
        exit 1
    }
} else {
    Write-Host "[EOU] uv found: $(uv --version)" -ForegroundColor Green
}

# 2. Create virtual environment
if (-not (Test-Path ".venv")) {
    Write-Host "[EOU] Creating .venv..." -ForegroundColor Cyan
    uv venv
} else {
    Write-Host "[EOU] .venv exists, reusing." -ForegroundColor Green
}

# 3. Install eou with full + windows-extra
Write-Host "[EOU] Installing eou[full,windows-extra] (editable)..." -ForegroundColor Cyan
uv pip install -e ".[full,windows-extra]"

# 4. Verify
Write-Host "[EOU] Verifying installation..." -ForegroundColor Cyan
& .\.venv\Scripts\eou.exe --help | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[EOU] Install complete." -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "  .\.venv\Scripts\Activate.ps1"
    Write-Host "  eou host   --config configs\eou.example.yaml    # HOST PC"
    Write-Host "  eou remote --config configs\eou.example.yaml    # REMOTE PC"
} else {
    Write-Error "eou CLI verification failed."
    exit 1
}

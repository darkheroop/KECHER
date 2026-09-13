#requires -Version 5.1
<#
    One-click local setup + start for the Telegram File Bot.

    Usage:
        .\run.ps1                 # set up (first time) and start the bot
        .\run.ps1 -SetupOnly      # only prepare venv/.env, do not start
        .\run.ps1 -Reinstall      # force reinstall dependencies
        .\run.ps1 -SkipInstall    # never run pip

    If PowerShell blocks scripts, either run:
        powershell -ExecutionPolicy Bypass -File .\run.ps1
    or double-click run.bat
#>
[CmdletBinding()]
param(
    [switch]$Reinstall,
    [switch]$SetupOnly,
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

function Write-Info($msg) { Write-Host "[setup] $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "[warn]  $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[error] $msg" -ForegroundColor Red }

function Write-EnvFile {
    param([string]$Path, [string[]]$Lines)
    [System.IO.File]::WriteAllLines($Path, [string[]]$Lines, (New-Object System.Text.UTF8Encoding($false)))
}

function Set-EnvValue {
    param([string]$Path, [string]$Key, [string]$Value)
    $lines = @()
    if (Test-Path -LiteralPath $Path) { $lines = @(Get-Content -LiteralPath $Path) }
    $found = $false
    $updated = foreach ($line in $lines) {
        if ($line -match "^\s*$([regex]::Escape($Key))\s*=") {
            $found = $true
            "$Key=$Value"
        }
        else { $line }
    }
    if (-not $found) { $updated = @($updated) + "$Key=$Value" }
    Write-EnvFile -Path $Path -Lines @($updated)
}

function Get-EnvValue {
    param([string]$Path, [string]$Key)
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match "^\s*$([regex]::Escape($Key))\s*=\s*(.*)$") { return $Matches[1].Trim() }
    }
    return ''
}

# --------------------------------------------------------------------------- #
# 1. Locate Python 3.11+
# --------------------------------------------------------------------------- #
$pythonExe = $null
foreach ($candidate in @('py', 'python')) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) { $pythonExe = $candidate; break }
}
if (-not $pythonExe) {
    Write-Err "Python 3.11+ was not found. Install it from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'."
    exit 1
}
$versionOk = (& $pythonExe -c "import sys; print(1 if sys.version_info >= (3, 11) else 0)" | Select-Object -Last 1)
if ($versionOk -ne '1') {
    Write-Err "Python 3.11 or newer is required. Found: $(& $pythonExe --version)"
    exit 1
}
Write-Info "Using $(& $pythonExe --version)"

# --------------------------------------------------------------------------- #
# 2. Virtual environment
# --------------------------------------------------------------------------- #
$venvDir = Join-Path $Root '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Info "Creating virtual environment (.venv)..."
    & $pythonExe -m venv $venvDir
    if (-not (Test-Path -LiteralPath $venvPython)) { Write-Err "Could not create the virtual environment."; exit 1 }
    $Reinstall = $true
}

if ($Reinstall -and -not $SkipInstall) {
    Write-Info "Installing dependencies (a few minutes the first time)..."
    & $venvPython -m pip install --upgrade pip --quiet
    & $venvPython -m pip install -r (Join-Path $Root 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { Write-Err "Dependency installation failed."; exit 1 }
}

# --------------------------------------------------------------------------- #
# 3. Local .env (free defaults: SQLite, no paid services)
# --------------------------------------------------------------------------- #
$envFile = Join-Path $Root '.env'
$placeholder = 'PASTE_YOUR_TOKEN_HERE'

if (-not (Test-Path -LiteralPath $envFile)) {
    Write-Info "Creating .env with local (free) defaults..."
    Write-EnvFile -Path $envFile -Lines @(
        "BOT_TOKEN=$placeholder",
        "ENVIRONMENT=development",
        "DATABASE_URL=sqlite+aiosqlite:///./var/app.db",
        "STORAGE_ROOT=./var/storage",
        "MAX_FILE_SIZE_MB=20",
        "LOG_LEVEL=INFO"
    )
}

$token = Get-EnvValue -Path $envFile -Key 'BOT_TOKEN'
if ([string]::IsNullOrWhiteSpace($token) -or $token -eq $placeholder) {
    Write-Host ""
    Write-Host "Paste your bot token from @BotFather, then press Enter." -ForegroundColor Cyan
    Write-Host "(Stored only in the local .env file. Never shared.)" -ForegroundColor DarkGray
    $secure = Read-Host "BOT_TOKEN" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    $plain = $plain.Trim()
    if ([string]::IsNullOrWhiteSpace($plain)) { Write-Err "No token entered."; exit 1 }
    if ($plain -notmatch '^\d{6,}:[A-Za-z0-9_-]{30,}$') {
        Write-Warn "That does not look like a standard bot token, continuing anyway."
    }
    Set-EnvValue -Path $envFile -Key 'BOT_TOKEN' -Value $plain
    Write-Info "Token saved to .env"
}

if ($SetupOnly) {
    Write-Info "Setup complete. Start the bot with:  .\run.ps1"
    exit 0
}

# --------------------------------------------------------------------------- #
# 4. Self-check, then run
# --------------------------------------------------------------------------- #
New-Item -ItemType Directory -Force -Path (Join-Path $Root 'var') | Out-Null
Write-Info "Running self-check..."
& $venvPython -m bot.tools.selfcheck
if ($LASTEXITCODE -ne 0) {
    Write-Err "Self-check failed. Fix the issue above, then run again."
    exit 1
}

Write-Info "Starting the bot... press Ctrl+C to stop."
Write-Host ""
& $venvPython -m bot.main

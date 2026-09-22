# setup.ps1 - one-time first-run setup for the SMDsmart ETL.
# Run this once per machine: right-click > Run with PowerShell, or from a
# PowerShell prompt: .\setup.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
Set-Location $ScriptDir

function Write-Step($msg) { Write-Host "`n== $msg ==" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!]  $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  [X]  $msg" -ForegroundColor Red }

Write-Host "SMDsmart ETL - first-time setup" -ForegroundColor White
Write-Host "Working in: $ScriptDir`n"

# --- 1. Python -----------------------------------------------------------
Write-Step "Checking Python"
try {
    $pyVersion = python --version 2>&1
    Write-Ok "$pyVersion found"
} catch {
    Write-Fail "Python not found on PATH. Install Python 3.10+ from python.org, "
    Write-Fail "make sure 'Add python.exe to PATH' is checked during install, then re-run this script."
    exit 1
}

# --- 2. pip dependencies ---------------------------------------------------
Write-Step "Installing Python dependencies (requirements.txt)"
if (-not (Test-Path (Join-Path $ScriptDir "requirements.txt"))) {
    Write-Fail "requirements.txt not found in $ScriptDir - are you running this from the etl folder?"
    exit 1
}
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Fail "pip install failed - see output above."
    exit 1
}
Write-Ok "Dependencies installed"

# --- 3. ODBC Driver for SQL Server ----------------------------------------
Write-Step "Checking for ODBC Driver for SQL Server"
$odbcDrivers = Get-OdbcDriver | Where-Object { $_.Name -like "*ODBC Driver*SQL Server*" }
if ($odbcDrivers) {
    $odbcDrivers | ForEach-Object { Write-Ok $_.Name }
} else {
    Write-Warn "No 'ODBC Driver for SQL Server' found. pyodbc needs one installed."
    Write-Warn "Download the free driver (17 or 18) from:"
    Write-Warn "  https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server"
    Write-Warn "Install it, then set SQL_DRIVER in .env to match the exact name it installs as."
}

# --- 4. .env file ----------------------------------------------------------
Write-Step "Checking .env configuration"
$envPath = Join-Path $ScriptDir ".env"
$envExamplePath = Join-Path $ScriptDir ".env.example"
if (Test-Path $envPath) {
    Write-Ok ".env already exists - leaving it untouched (not overwriting configured credentials)"
} elseif (Test-Path $envExamplePath) {
    Copy-Item $envExamplePath $envPath
    Write-Warn ".env created from .env.example - YOU MUST EDIT IT before running the ETL:"
    Write-Warn "  SQL_SERVER, SQL_DATABASE, SQL_TRUSTED_CONNECTION (or SQL_USERNAME/PASSWORD), NAS_ROOT"
} else {
    Write-Fail ".env.example not found - cannot create .env automatically. See README.md."
}

# --- 5. logs folder ----------------------------------------------------------
Write-Step "Preparing logs folder"
$logDir = Join-Path $ScriptDir "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
    Write-Ok "Created logs/"
} else {
    Write-Ok "logs/ already exists"
}

# --- Summary -----------------------------------------------------------------
Write-Step "Setup finished - next steps"
Write-Host @"
  1. Edit .env with your real SQL Server connection details (if not already done).
  2. Run dwh_schema.sql against your target database (SSMS/Azure Data Studio/sqlcmd)
     - only needed once, before the first ETL run.
  3. Test the connection: python run_etl.py
  4. Once that runs clean, import SMDsmart_ETL_Task.xml into Task Scheduler
     for daily automation (see System_Documentation.md section 4).
"@ -ForegroundColor White

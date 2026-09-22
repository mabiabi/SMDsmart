# run_etl.ps1 - wrapper for scheduled execution of the SMDsmart ETL.
# Handles: correct working directory regardless of how Task Scheduler
# invokes it, exit-code checking, wrapper-level logging, and an optional
# email alert on failure.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$PythonExe = "python"   # change to a full path if you're using a specific venv, e.g.:
                         # "C:\Users\<youruser>\Desktop\SMDsmart_DWH\etl\.venv\Scripts\python.exe"

$LogDir = Join-Path $ScriptDir "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$WrapperLog = Join-Path $LogDir "wrapper_$Timestamp.log"

# --- Optional email alert on failure -------------------------------------
# Leave $EnableEmailAlert = $false to skip entirely (the wrapper log file
# and Task Scheduler's own history are still there either way).
$EnableEmailAlert = $false
$SmtpServer = "smtp.example.com"
$SmtpPort = 587
$SmtpFrom = "etl-alerts@smdsmart.local"
$SmtpTo = "you@smdsmart.local"
$SmtpUser = "etl-alerts@smdsmart.local"
# Store the SMTP password as an encrypted string in this file, never in
# plain text / never in source control. One-time setup (run once, as the
# SAME Windows user the scheduled task will run as):
#   Read-Host "SMTP password" -AsSecureString | ConvertFrom-SecureString | Out-File smtp_password.txt
$SmtpPasswordFile = Join-Path $ScriptDir "smtp_password.txt"

function Send-FailureAlert {
    param([string]$ErrorDetail)
    if (-not $EnableEmailAlert) { return }
    try {
        $securePassword = Get-Content $SmtpPasswordFile | ConvertTo-SecureString
        $cred = New-Object System.Management.Automation.PSCredential($SmtpUser, $securePassword)
        Send-MailMessage -From $SmtpFrom -To $SmtpTo -Subject "SMDsmart ETL FAILED - $Timestamp" `
            -Body "The scheduled ETL run failed. Wrapper log attached.`n`n$ErrorDetail" `
            -SmtpServer $SmtpServer -Port $SmtpPort -UseSsl -Credential $cred `
            -Attachments $WrapperLog
    } catch {
        Add-Content -Path $WrapperLog -Value "Failed to send alert email: $_"
    }
}

"=== SMDsmart ETL wrapper started $Timestamp ===" | Tee-Object -FilePath $WrapperLog -Append

try {
    & $PythonExe run_etl.py 2>&1 | Tee-Object -FilePath $WrapperLog -Append
    if ($LASTEXITCODE -ne 0) {
        throw "run_etl.py exited with code $LASTEXITCODE (check the etl_$((Get-Date).ToString('yyyyMMdd')).log for which branch failed)"
    }
    "=== ETL completed successfully ===" | Tee-Object -FilePath $WrapperLog -Append
    exit 0
} catch {
    "=== ETL FAILED: $_ ===" | Tee-Object -FilePath $WrapperLog -Append
    Send-FailureAlert -ErrorDetail $_
    exit 1
}

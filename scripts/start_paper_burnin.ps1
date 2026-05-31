$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$BurninDir = Join-Path $Root "state\burnin"
$PidPath = Join-Path $BurninDir "paper-burnin.pid"
$MetadataPath = Join-Path $BurninDir "metadata.json"
$StdoutPath = Join-Path $BurninDir "stdout.log"
$StderrPath = Join-Path $BurninDir "stderr.log"

if (-not (Test-Path $Python)) {
    throw "Project virtual environment Python is missing: $Python"
}

New-Item -ItemType Directory -Force -Path $BurninDir | Out-Null

if (Test-Path $PidPath) {
    $ExistingPid = Get-Content $PidPath -Raw
    if ($ExistingPid -and (Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue)) {
        Write-Output "Paper burn-in already running with PID $ExistingPid"
        exit 0
    }
}

$env:TRA_KITE_API_KEY = ""
$env:TRA_KITE_API_SECRET = ""
$env:TRA_KITE_ACCESS_TOKEN = ""
$env:TRA_KITE_USER_ID = ""
$env:TRA_EVENT_STORE_TYPE = "sqlite"
$env:TRA_DASHBOARD = "0"
$env:TRA_DASHBOARD_TYPE = "http"
$env:TRA_METRICS_PORT = "8080"
$env:TRA_BURNIN = "1"
$env:TRA_BURNIN_RECONCILIATION_SECONDS = "1800"
$env:TRA_BURNIN_RECONCILIATION_PATH = "state/burnin/reconciliation.jsonl"
$env:TRA_WATCHLIST = "RELIANCE-EQ,INFY-EQ,HDFCBANK-EQ"

$Process = Start-Process `
    -FilePath $Python `
    -ArgumentList "-m", "src.main" `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $StdoutPath `
    -RedirectStandardError $StderrPath `
    -WindowStyle Hidden `
    -PassThru

$StartedAt = (Get-Date).ToUniversalTime()
$EndsAt = $StartedAt.AddHours(24)

Set-Content -Path $PidPath -Value $Process.Id
@{
    pid = $Process.Id
    started_at = $StartedAt.ToString("o")
    ends_at = $EndsAt.ToString("o")
    mode = "paper"
    market_data = "angel_websocket"
    reconciliation_interval_seconds = 1800
} | ConvertTo-Json -Depth 10 | Set-Content -Path $MetadataPath

Write-Output "Paper burn-in started with PID $($Process.Id)"
Write-Output "Metrics: http://localhost:8080/metrics"
Write-Output "Health: http://localhost:8080/health"

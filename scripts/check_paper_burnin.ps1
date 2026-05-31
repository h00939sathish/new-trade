$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BurninDir = Join-Path $Root "state\burnin"
$PidPath = Join-Path $BurninDir "paper-burnin.pid"
$MetadataPath = Join-Path $BurninDir "metadata.json"
$ReconciliationPath = Join-Path $BurninDir "reconciliation.jsonl"
$StderrPath = Join-Path $BurninDir "stderr.log"

$Result = [ordered]@{
    checked_at = (Get-Date).ToUniversalTime().ToString("o")
    process_running = $false
    health_reachable = $false
    metrics_reachable = $false
    metadata = $null
    reconciliation = $null
    recent_errors = @()
}

if (Test-Path $PidPath) {
    $BurninPid = Get-Content $PidPath -Raw
    if ($BurninPid -and (Get-Process -Id $BurninPid -ErrorAction SilentlyContinue)) {
        $Result.process_running = $true
    }
}

if (Test-Path $MetadataPath) {
    $Result.metadata = Get-Content $MetadataPath -Raw | ConvertFrom-Json
}

try {
    $Result.health = Invoke-RestMethod -Uri "http://localhost:8080/health" -TimeoutSec 10
    $Result.health_reachable = $true
}
catch {
    $Result.health_error = $_.Exception.Message
}

try {
    Invoke-WebRequest -Uri "http://localhost:8080/metrics" -TimeoutSec 10 | Out-Null
    $Result.metrics_reachable = $true
}
catch {
    $Result.metrics_error = $_.Exception.Message
}

if (Test-Path $ReconciliationPath) {
    $Latest = Get-Content $ReconciliationPath -Tail 1
    if ($Latest) {
        $Result.reconciliation = $Latest | ConvertFrom-Json
    }
}

if (Test-Path $StderrPath) {
    $Result.recent_errors = @(
        Get-Content $StderrPath -Tail 100 |
            Select-String -Pattern "\] ERROR:|Traceback|Exception:" |
            Select-Object -Last 10 |
            ForEach-Object { $_.Line }
    )
}

$Result | ConvertTo-Json -Depth 10

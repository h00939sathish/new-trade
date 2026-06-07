# run_paper_5d.ps1 - 5-day paper trading burn-in wrapper (Windows)
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\run_paper_5d.ps1
#
# Features:
#   - Forces paper-only mode (clears Kite creds)
#   - Auto-restarts on crash (5s backoff, max 10 restarts/day)
#   - Rotates stdout/stderr to state\burnin\day{N}.log daily
#   - Stops gracefully after 5 days, writes run_manifest.json
#   - Ctrl+C triggers cleanup of child process + partial manifest

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$BurninDir = Join-Path $Root "state\burnin"
$PidPath = Join-Path $BurninDir "paper-burnin.pid"
$ManifestPath = Join-Path $BurninDir "run_manifest.json"
$MaxRestartsPerDay = 10

if (-not (Test-Path $Python)) {
    throw "Project venv python missing: $Python"
}
New-Item -ItemType Directory -Force -Path $BurninDir | Out-Null

# Force paper-only env (defense-in-depth: clear Kite creds in child process)
$env:TRA_KITE_API_KEY = ""
$env:TRA_KITE_API_SECRET = ""
$env:TRA_KITE_ACCESS_TOKEN = ""
$env:TRA_KITE_USER_ID = ""
$env:TRA_LIVE_TRADING_ENABLED = "false"
$env:TRA_EVENT_STORE_TYPE = "sqlite"
$env:TRA_DASHBOARD = "0"
$env:TRA_DASHBOARD_TYPE = "http"
$env:TRA_METRICS_PORT = "8080"
$env:TRA_BURNIN = "1"
$env:TRA_BURNIN_RECONCILIATION_SECONDS = "300"
$env:TRA_BURNIN_RECONCILIATION_PATH = "state/burnin/reconciliation.jsonl"

# Phase 1 invariant env vars (set explicitly to avoid .env drift)
$env:TRA_CONSENSUS_THRESHOLD = "0.65"
$env:TRA_CONSENSUS_SHORT_THRESHOLD = "0.70"
$env:TRA_SIGNAL_COOLDOWN_SECONDS = "120"
$env:TRA_KILL_SWITCH_DAILY_LOSS_PCT = "0.01"
$env:TRA_KILL_SWITCH_MAX_DRAWDOWN_PCT = "0.05"
$env:TRA_REFLECTION_MUTATION_ENABLED = "false"
$env:TRA_RISK_PER_TRADE_LOSS_CAP_PCT = "0.01"

$StartTime = Get-Date
$EndTime = $StartTime.AddDays(5)
$Day = 1
$TotalCrashes = 0
$StopRequested = $false
$ActiveProcess = $null

# Ctrl+C handler: mark stop, kill child, write manifest
$null = [Console]::TreatControlCAsInput = $false
$handler = {
    Write-Output ""
    Write-Output "[$(Get-Date -Format 'o')] Ctrl+C received. Stopping burn-in..."
    $script:StopRequested = $true
    if ($null -ne $script:ActiveProcess -and -not $script:ActiveProcess.HasExited) {
        Stop-Process -Id $script:ActiveProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
[Console]::add_CancelKeyPress($handler)

Write-Output "[$(Get-Date -Format 'o')] Paper 5-day burn-in starting. End scheduled: $($EndTime.ToString('o'))"
Write-Output "Logs: $BurninDir\day{N}.log (stdout) and day{N}_stderr.log (stderr)"

while ((Get-Date) -lt $EndTime -and -not $StopRequested) {
    $DayStart = Get-Date
    $DayEnd = $DayStart.AddDays(1).AddSeconds(-1)  # Day boundary ~midnight
    $DayLog = Join-Path $BurninDir "day${Day}.log"
    $DayErr = Join-Path $BurninDir "day${Day}_stderr.log"
    $DayRestarts = 0

    Write-Output ""
    Write-Output "[$(Get-Date -Format 'o')] === Day $Day starting ==="
    Write-Output "  Log: $DayLog"
    Write-Output "  Day ends at: $($DayEnd.ToString('o'))"

    while ((Get-Date) -lt $DayEnd -and (Get-Date) -lt $EndTime -and -not $StopRequested) {
        Write-Output "[$(Get-Date -Format 'o')] Starting python -m src.main (attempt $($DayRestarts + 1))..."

        $ActiveProcess = Start-Process `
            -FilePath $Python `
            -ArgumentList "-m", "src.main" `
            -WorkingDirectory $Root `
            -RedirectStandardOutput $DayLog `
            -RedirectStandardError $DayErr `
            -WindowStyle Hidden `
            -PassThru

        Set-Content -Path $PidPath -Value $ActiveProcess.Id
        $ActiveProcess.WaitForExit() | Out-Null

        $ExitCode = $ActiveProcess.ExitCode
        $ActiveProcess = $null
        Remove-Item -LiteralPath $PidPath -ErrorAction SilentlyContinue

        if ($StopRequested) {
            break
        }

        if ($ExitCode -eq 0) {
            Write-Output "[$(Get-Date -Format 'o')] Process exited cleanly (code=0). Restarting..."
        }
        else {
            $TotalCrashes++
            $DayRestarts++
            Write-Output "[$(Get-Date -Format 'o')] CRASH exit=$ExitCode. Total crashes: $TotalCrashes. Day $Day restarts: $DayRestarts."

            if ($DayRestarts -ge $MaxRestartsPerDay) {
                Write-Output "[$(Get-Date -Format 'o')] FATAL: $MaxRestartsPerDay restarts in day $Day. Aborting burn-in."
                $StopRequested = $true
                break
            }
        }

        # Backoff before restart
        Start-Sleep -Seconds 5
    }

    $Day++

    if ((Get-Date) -ge $EndTime) {
        Write-Output "[$(Get-Date -Format 'o')] 5-day window elapsed."
        break
    }
}

# Write final manifest
$Manifest = [ordered]@{
    started_at = $StartTime.ToString("o")
    ended_at = (Get-Date).ToString("o")
    ended_reason = $(if ($StopRequested) { "stopped_by_operator_or_crash_loop" } else { "completed_5_days" })
    days_completed = $Day - 1
    total_crashes = $TotalCrashes
    watchlist = $env:TRA_WATCHLIST
    consensus_threshold = $env:TRA_CONSENSUS_THRESHOLD
    kill_switch_daily_loss_pct = $env:TRA_KILL_SWITCH_DAILY_LOSS_PCT
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -Path $ManifestPath

Write-Output ""
Write-Output "[$(Get-Date -Format 'o')] === Burn-in ended ==="
Write-Output "Manifest: $ManifestPath"
Write-Output "Days completed: $($Day - 1)"
Write-Output "Total crashes: $TotalCrashes"

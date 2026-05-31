$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$PidPath = Join-Path $Root "state\burnin\paper-burnin.pid"

if (-not (Test-Path $PidPath)) {
    Write-Output "Paper burn-in PID file is missing"
    exit 0
}

$BurninPid = Get-Content $PidPath -Raw
$Process = Get-Process -Id $BurninPid -ErrorAction SilentlyContinue
if ($Process) {
    Stop-Process -Id $BurninPid
    Write-Output "Stopped paper burn-in PID $BurninPid"
}
else {
    Write-Output "Paper burn-in process $BurninPid is not running"
}

Remove-Item -LiteralPath $PidPath -ErrorAction SilentlyContinue

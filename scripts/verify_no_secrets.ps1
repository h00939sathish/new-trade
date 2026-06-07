#!/usr/bin/env pwsh
# Verify no broker credentials are leaked in current working tree (NOT history)
# Reads only the *current* files, not git history.
# This is a fast pre-commit/post-commit guard; the heavy history scrub is in
# scripts/scrub_credentials.{ps1,sh} (uses git-filter-repo).
#
# Exit codes:
#   0  no leaks
#   1  one or more leaks detected
#   2  internal error

$ErrorActionPreference = "Stop"

Set-Location (git rev-parse --show-toplevel)

# Patterns: project-specific env vars + generic high-entropy secrets
# PowerShell regex: use single-quoted strings to avoid backslash escaping issues.
$patterns = @(
    @{ Name = "Kite API key";        Regex = 'TRA_KITE_API_KEY\s*=\s*[A-Za-z0-9]{16,}' },
    @{ Name = "Kite access token";   Regex = 'TRA_KITE_ACCESS_TOKEN\s*=\s*[A-Za-z0-9]{16,}' },
    @{ Name = "Groww auth token";    Regex = 'TRA_GROWW_AUTH_TOKEN\s*=\s*[A-Za-z0-9]{40,}' },
    @{ Name = "Angel API key";       Regex = 'TRA_ANGEL_API_KEY\s*=\s*[A-Za-z0-9]{16,}' },
    @{ Name = "Generic api_key=";    Regex = '(?i)api[_\-]?key\s*[=:]\s*[''"]?[A-Za-z0-9]{20,}' },
    @{ Name = "Generic secret=";     Regex = '(?i)secret\s*[=:]\s*[''"]?[A-Za-z0-9]{20,}' },
    @{ Name = "JWT (eyJ...)";        Regex = 'eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}' }
)

# Files to scan: tracked files only. .env is intentionally gitignored and
# contains real secrets for local dev; that's not the leak we care about.
# The leak we care about is real values getting committed to a tracked file.
$files = git ls-files

$leaks = New-Object System.Collections.ArrayList
foreach ($f in $files) {
    $content = $null
    try {
        $content = Get-Content -LiteralPath $f -Raw -ErrorAction Stop
    } catch {
        continue
    }
    if (-not $content) { continue }
    foreach ($p in $patterns) {
        try {
            $matches = [regex]::Matches($content, $p.Regex)
        } catch {
            Write-Warning "Bad regex for $($p.Name): $($_.Exception.Message)"
            continue
        }
        foreach ($m in $matches) {
            $truncated = $m.Value
            if ($truncated.Length -gt 50) { $truncated = $truncated.Substring(0, 50) }
            [void]$leaks.Add([pscustomobject]@{
                File    = $f
                Pattern = $p.Name
                Match   = $truncated
            })
        }
    }
}

if ($leaks.Count -eq 0) {
    Write-Host "CLEAN: no broker credentials detected in working tree" -ForegroundColor Green
    exit 0
}

Write-Host "LEAK DETECTED:" -ForegroundColor Red
$leaks | Format-Table -AutoSize
exit 1

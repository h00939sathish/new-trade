#!/usr/bin/env pwsh
# Scrub leaked credentials from git history
# REQUIRES: git-filter-repo (pip install git-filter-repo)
# WARNING: This rewrites all commits. Force-push required. Coordinate with collaborators.

$ErrorActionPreference = "Stop"

# Check for git-filter-repo
$hasFilterRepo = $null -ne (Get-Command git-filter-repo -ErrorAction SilentlyContinue)
if (-not $hasFilterRepo) {
    Write-Host "git-filter-repo not installed. Install with: pip install git-filter-repo" -ForegroundColor Red
    exit 1
}

Set-Location (git rev-parse --show-toplevel)

Write-Host "This will rewrite ALL commits in this repo to remove credentials from history." -ForegroundColor Yellow
Write-Host "After this, you must force-push: git push origin --force --all" -ForegroundColor Yellow
Write-Host ""
$confirm = Read-Host "Continue? (type 'yes' to proceed)"
if ($confirm -ne "yes") {
    Write-Host "Aborted."
    exit 1
}

Write-Host "1. Removing .env from all history..." -ForegroundColor Cyan
git filter-repo --invert-paths --path .env

Write-Host "2. Replacing leaked credential values in all history..." -ForegroundColor Cyan
$replacements = @"
k1bpotx2f133yrms==>REDACTED
fpb0y4jus1pnv5d7kkh1zm6xyrmofv0s==>REDACTED
7xTDqWZ7hOQCpicWT9EiR3a6fYV7uRLa==>REDACTED
NXX826==>REDACTED
njAvCMjm==>REDACTED
S53924079==>REDACTED
2217==>REDACTED
ZSIJKEMSPC2CFTN4ROJRVXKA5UL2ZZSW==>REDACTED
"@
$tmp = [System.IO.Path]::GetTempFileName()
Set-Content -LiteralPath $tmp -Value $replacements
git filter-repo --replace-text $tmp
Remove-Item $tmp

Write-Host ""
Write-Host "Done. Verify with:" -ForegroundColor Green
Write-Host "  git log --all -p | Select-String 'TRA_KITE|TRA_GROWW|TRA_ANGEL' | Select-Object -First 5"
Write-Host "  (Expected: no output)"
Write-Host ""
Write-Host "Then force-push:" -ForegroundColor Yellow
Write-Host "  git push origin --force --all"
Write-Host "  git push origin --force --tags"
Write-Host ""
Write-Host "Notify all collaborators to re-clone." -ForegroundColor Yellow

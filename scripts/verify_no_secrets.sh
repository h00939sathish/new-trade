#!/usr/bin/env bash
# Verify no broker credentials are leaked in current working tree (NOT history).
# See scripts/verify_no_secrets.ps1 for full docs (mirror of this file).
#
# Exit codes:
#   0  no leaks
#   1  one or more leaks detected
#   2  internal error

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

PATTERNS=(
    "TRA_KITE_API_KEY[[:space:]]*=[[:space:]]*[A-Za-z0-9]{16,}|Kite API key"
    "TRA_KITE_ACCESS_TOKEN[[:space:]]*=[[:space:]]*[A-Za-z0-9]{16,}|Kite access token"
    "TRA_GROWW_AUTH_TOKEN[[:space:]]*=[[:space:]]*[A-Za-z0-9]{40,}|Groww auth token"
    "TRA_ANGEL_API_KEY[[:space:]]*=[[:space:]]*[A-Za-z0-9]{16,}|Angel API key"
    "[aA][pP][iI][_-][kK][eE][yY][[:space:]]*[:=][[:space:]]*['\"]?[A-Za-z0-9]{20,}|Generic api_key"
    "[sS][eE][cC][rR][eE][tT][[:space:]]*[:=][[:space:]]*['\"]?[A-Za-z0-9]{20,}|Generic secret"
    "eyJ[A-Za-z0-9_-]{20,}\\.[A-Za-z0-9_-]{20,}|JWT"
)

files=$(git ls-files)
if [ -f .env ]; then files="$files"$'\n'.env; fi

leaks=0
for f in $files; do
    [ -f "$f" ] || continue
    content=$(cat "$f" 2>/dev/null || true)
    [ -z "$content" ] && continue
    for entry in "${PATTERNS[@]}"; do
        regex="${entry%%|*}"
        label="${entry##*|}"
        if echo "$content" | grep -E -q "$regex" 2>/dev/null; then
            hits=$(echo "$content" | grep -E -o "$regex" | head -3)
            while IFS= read -r hit; do
                truncated="${hit:0:50}"
                echo "LEAK: $f [$label] $truncated" >&2
                leaks=$((leaks+1))
            done <<< "$hits"
        fi
    done
done

if [ "$leaks" -eq 0 ]; then
    echo "CLEAN: no broker credentials detected in working tree"
    exit 0
fi

echo "FAIL: $leaks leak(s) detected" >&2
exit 1

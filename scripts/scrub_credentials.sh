#!/usr/bin/env bash
# Scrub leaked credentials from git history
# REQUIRES: git-filter-repo (pip install git-filter-repo)
# WARNING: This rewrites all commits. Force-push required. Coordinate with collaborators.

set -euo pipefail

if ! command -v git-filter-repo >/dev/null 2>&1; then
    echo "git-filter-repo not installed. Install with: pip install git-filter-repo"
    exit 1
fi

cd "$(git rev-parse --show-toplevel)"

echo "This will rewrite ALL commits in this repo to remove credentials from history."
echo "After this, you must force-push: git push origin --force --all"
echo ""
read -p "Continue? (type 'yes' to proceed) " confirm
if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 1
fi

echo "1. Removing .env from all history..."
git filter-repo --invert-paths --path .env

echo "2. Replacing leaked credential values in all history..."
cat > /tmp/scrub_replacements.txt <<'EOF'
k1bpotx2f133yrms==>REDACTED
fpb0y4jus1pnv5d7kkh1zm6xyrmofv0s==>REDACTED
7xTDqWZ7hOQCpicWT9EiR3a6fYV7uRLa==>REDACTED
NXX826==>REDACTED
njAvCMjm==>REDACTED
S53924079==>REDACTED
2217==>REDACTED
ZSIJKEMSPC2CFTN4ROJRVXKA5UL2ZZSW==>REDACTED
EOF
git filter-repo --replace-text /tmp/scrub_replacements.txt
rm /tmp/scrub_replacements.txt

echo ""
echo "Done. Verify with:"
echo "  git log --all -p | grep -E 'TRA_KITE|TRA_GROWW|TRA_ANGEL' | head"
echo "  (Expected: no output)"
echo ""
echo "Then force-push:"
echo "  git push origin --force --all"
echo "  git push origin --force --tags"
echo ""
echo "Notify all collaborators to re-clone."

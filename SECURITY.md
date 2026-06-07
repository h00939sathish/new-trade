# Security — Credential Leak Remediation

> **STATUS (2026-06-07 audit remediation, Wave 1 Task 1):**
> - ✅ `scripts/verify_no_secrets.{ps1,sh}` created (working-tree guard, fast, run on every commit)
> - ✅ `scripts/scrub_credentials.{ps1,sh}` already exist (history scrub via git-filter-repo)
> - ⚠️  **History scrub not yet executed** — credentials (`k1bpotx2f133yrms`, etc.) are still present in git history. Force-push required. See "Pending Action" below.
>
> This repo's `.env` was committed in the initial commit (`68c373a`) and deleted in `277e031`. The credentials below are baked into git history. They must be considered compromised.

## Pending Action (REQUIRES USER CONFIRMATION)

A full history scrub is **destructive and shared-impact**: it rewrites all commits and requires `git push --force` to `https://github.com/aisathish07/new-trade.git`. This affects any collaborators on the same branch.

To execute (manual, two-step):

```pwsh
# 1. install git-filter-repo
pip install git-filter-repo

# 2. scrub (will prompt for confirmation)
pwsh scripts/scrub_credentials.ps1

# 3. force-push (only after confirming no collaborators are active)
git push origin --force --all
git push origin --force --tags
```

The user must run these steps manually; this task only created the verifier scripts and documented the procedure.

## Compromised Credentials

The following tokens were exposed in git history and **must be revoked and re-issued** at the respective broker portals:

### Kite (Zerodha)
- `TRA_KITE_API_KEY`
- `TRA_KITE_API_SECRET`
- `TRA_KITE_ACCESS_TOKEN`
- `TRA_KITE_USER_ID`

**Revoke/re-issue:** https://kite.trade → Apps → Regenerate API secret → Re-login to get a new access token.

### Groww
- `TRA_GROWW_API_KEY`
- `TRA_GROWW_API_SECRET`
- `TRA_GROWW_TOTP_SECRET`
- `TRA_GROWW_AUTH_TOKEN`

**Revoke/re-issue:** Groww does not have a self-serve token rotation portal. Contact Groww support or wait for the tokens to expire (the auth token shows `exp: 2565098927` which is far-future — manual revocation is required).

### Angel One
- `TRA_ANGEL_API_KEY`
- `TRA_ANGEL_CLIENT_ID`
- `TRA_ANGEL_PASSWORD`
- `TRA_ANGEL_TOTP`

**Revoke/re-issue:** Change your Angel One password and regenerate the TOTP secret in the Angel One app.

## Remediation Steps

1. **Revoke** all the tokens above at the broker portals (steps above).
2. **Re-issue** new tokens.
3. **Update** your local `.env` with the new tokens. Do NOT commit the new `.env`.
4. **Scrub** git history to remove the leaked tokens:
   ```bash
   # Using git-filter-repo (recommended)
   pip install git-filter-repo
   git filter-repo --invert-paths --path .env
   # Or replace text patterns:
   git filter-repo --replace-text expressions.txt
   ```
5. **Force-push** the cleaned history:
   ```bash
   git remote add origin <your-remote-url>
   git push origin --force --all
   git push origin --force --tags
   ```
6. **Notify** any collaborators that they must re-clone (or do `git rebase --onto`).
7. **Verify** the leak is gone:
   ```bash
   git log --all -p | grep -E "TRA_KITE|TRA_GROWW|TRA_ANGEL" | head
   # Expected: no output
   ```

## Prevention

This repo now includes:
- `.gitignore` entry for `.env` (already in place).
- `.githooks/pre-commit` credential scanner (see below).
- This `SECURITY.md` as a permanent record.

### Pre-commit Hook

The pre-commit hook scans for credential patterns. Install it:
```bash
git config core.hooksPath .githooks
```

Patterns detected:
- `TRA_KITE_*`, `TRA_GROWW_*`, `TRA_ANGEL_*` (Kite, Groww, Angel tokens)
- Generic patterns: `api_key=...`, `secret=...`, `password=...`, `token=...`
- JWT tokens (`eyJ...`)

## If You Discover a New Leak

1. Do NOT push the change.
2. Revoke the credentials at the broker.
3. Open a security issue (do not include the leaked value in the issue).
4. Follow the remediation steps above.

## Contact

For questions about this remediation, contact the repo owner.

# poller

The audit-log sync poller. A scheduled Lambda reads the GitHub org audit log,
collapses events to the set of touched teams, and reconciles each against IAM
Identity Center. It works on the **delta** (not the whole org) and is **dry-run
by default** — it only writes when `NOT_DRY_RUN=true`.

The pure logic core performs no I/O and is unit-testable with no credentials.
The write path performs only three verbs — create group, add member, remove
member — with no destructive operations (group/user deletion is the nightly
reconciler's job).

## Layout

```
src/scim_sync/
  models.py            # plain immutable data types
  config.py            # env-based config (+ Secrets Manager token fetch)
  pipeline.py          # shared poll -> build-plans orchestration
  apply.py             # applies plans, gated by dry-run
  handlers/
    poller.py          # Lambda entrypoint
  logic/
    audit_events.py    # raw audit entries -> set of touched teams/users
    watermark.py       # cursor advance logic (pure)
    diff.py            # desired vs actual members -> add/remove (pure)
    plan.py            # compose a TeamPlan + render dry-run text
  adapters/
    github_client.py   # httpx: audit log + team members (read-only)
    identity_store.py  # boto3: reads + the three permitted writes
    cursor_store.py    # SSM Parameter Store cursor (production)
    watermark_store.py # local JSON cursor (dry-run stand-in)
tests/
  unit/                # runs with no network/AWS/GitHub
  fixtures/audit_log/  # sample audit-log payloads
```

## Run the tests

Requires Python 3.13. With [uv](https://docs.astral.sh/uv/):

```sh
cd poller
uv run --python 3.13 --with pytest pytest -q
```

Or with an existing 3.13 environment:

```sh
pip install -e '.[dev]'
pytest -q
```

## What is deliberately NOT here yet

- The legacy v1 nightly **reconciler** (deletes empty groups + orphaned users).
- GitHub **App** (JWT) auth — a token is used for now.

## Dry run against the real org + Identity Center (read-only)

This polls the **real** org audit log and reconciles against the **real** Identity
Center, but only ever **reads** and prints what it *would* change. It also reports
how much less work the delta approach does than a full reconcile.

### 1. Set credentials in your env

```sh
export GITHUB_ORG="ministryofjustice"
# GitHub token: taken from GITHUB_TOKEN/GH_TOKEN, else falls back to `gh auth token`.
# Needs read:audit_log / admin:org read for the org audit log.
export GITHUB_TOKEN="$(gh auth token)"     # or paste your own

# AWS / Identity Center (paste your creds before running):
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_SESSION_TOKEN=...                # if using temporary creds
export AWS_REGION="eu-west-2"
export SSO_IDENTITY_STORE_ID="d-xxxxxxxxxx"  # optional: auto-discovered via sso-admin if unset
export SSO_EMAIL_SUFFIX="@digital.justice.gov.uk"

# optional
export LOOKBACK_MINUTES=60                  # first-run window if no watermark file
export WATERMARK_FILE=.watermark.json
```

### 2. Run it

```sh
cd poller
uv run --python 3.13 --extra live scim-dry-run
```

Add `--baseline` to also measure a real full-reconcile read pass and print the
API-call reduction for this cycle:

```sh
uv run --python 3.13 --extra live scim-dry-run -- --baseline
```

### What you'll see

- The dry-run plan: per team, the memberships it *would* add/remove (no-op teams summarised).
- **This run (delta):** audit events pulled, teams to reconcile, GitHub + Identity API calls.
- **With `--baseline`:** teams in the org, the full-reconcile API-call count, and the
  percentage reduction — the concrete efficiency comparison.

The watermark advances on each run and is saved to `WATERMARK_FILE`, so a second
run resumes from where the first stopped (delete the file to start over).

## Build & deploy (Lambda)

The Lambda runtime ships `boto3` but **not** `httpx`, so the deployment package
must vendor the `live` dependencies alongside the source.

```sh
cd poller
rm -rf build && mkdir -p build
# vendor runtime deps for the Lambda platform
uv pip install --python 3.13 --target build \
  --python-platform x86_64-manylinux2014 --only-binary=:all: httpx
# add the source
cp -r src/scim_sync build/scim_sync
# zip it
(cd build && zip -qr ../dist/poller.zip .)
```

Then deploy with Terraform (from `../terraform`):

```sh
terraform init
terraform apply \
  -var 'github_org=ministryofjustice' \
  -var 'github_app_secret_arn=arn:aws:secretsmanager:eu-west-2:...:secret:github_periodic_sync_app' \
  -var 'sso_email_suffix=@digital.justice.gov.uk' \
  -var 'lambda_package_path=../poller/dist/poller.zip'
  # not_dry_run defaults to false (shadow mode). Set -var 'not_dry_run=true' to go live.
```

The poller authenticates as a **GitHub App**. App credentials live in **one JSON
Secrets Manager secret** (so nothing app-specific is in Terraform or state):

```json
{ "app_id": "4175736", "installation_id": "143349949", "private_key": "-----BEGIN RSA PRIVATE KEY-----\n..." }
```

The poller reads it and mints a short-lived installation token per invocation.
For local dry runs the App vars are optional — it falls back to `GITHUB_TOKEN` /
`gh auth token`.

The handler is `scim_sync.handlers.poller.handler`. The audit-log cursor lives in
the SSM parameter `/<name>/audit_cursor`, owned by the Lambda (Terraform seeds a
placeholder and ignores subsequent value changes).

"""Environment-based configuration and GitHub auth resolution.

Reads everything from the environment so credentials are never committed.

GitHub auth is resolved at use time, in priority order:
  1. **GitHub App (JSON secret)** — ``GITHUB_APP_SECRET`` names a Secrets Manager
     secret whose value is JSON ``{app_id, installation_id, private_key}``. We read
     it and mint a short-lived installation token. (Production — nothing
     app-specific lives in Terraform.)
  2. **GitHub App (discrete)** — ``GITHUB_APP_ID`` + ``GITHUB_APP_INSTALLATION_ID``
     + the PEM in ``GITHUB_APP_PRIVATE_KEY_SECRET``. (Fallback.)
  3. ``GITHUB_TOKEN`` / ``GH_TOKEN`` from the environment. (CI / overrides.)
  4. ``gh auth token`` from the GitHub CLI. (Local dry-run convenience.)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Config:
    github_org: str
    identity_store_id: str | None
    aws_region: str | None
    email_suffix: str
    lookback_minutes: int
    watermark_file: str
    not_dry_run: bool
    cursor_parameter_name: str
    max_changes_per_run: int
    # On first run (no cursor), seed the window from this v1 Lambda's last
    # execution time to avoid a cutover gap. Empty -> use lookback_minutes.
    v1_lambda_name: str | None
    # GitHub auth inputs (all optional; resolved by resolve_github_token).
    # Preferred: one JSON secret with app_id, installation_id and private_key.
    github_app_secret: str | None
    # Discrete fallback (id/installation in env, key in its own secret).
    github_app_id: str | None
    github_app_installation_id: str | None
    github_app_private_key_secret: str | None
    github_token: str | None


def load() -> Config:
    org = os.environ.get("GITHUB_ORG")
    if not org:
        raise RuntimeError("GITHUB_ORG is required (the GitHub organisation to poll).")

    return Config(
        github_org=org,
        identity_store_id=os.environ.get("SSO_IDENTITY_STORE_ID"),
        aws_region=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
        email_suffix=os.environ.get("SSO_EMAIL_SUFFIX", ""),
        lookback_minutes=int(os.environ.get("LOOKBACK_MINUTES", "60")),
        watermark_file=os.environ.get("WATERMARK_FILE", ".watermark.json"),
        not_dry_run=os.environ.get("NOT_DRY_RUN", "").lower() in ("1", "true", "yes"),
        cursor_parameter_name=os.environ.get("AUDIT_CURSOR_PARAMETER", "/scim-sync/audit_cursor"),
        max_changes_per_run=int(os.environ.get("MAX_CHANGES_PER_RUN", "50")),
        v1_lambda_name=os.environ.get("V1_LAMBDA_NAME"),
        github_app_secret=os.environ.get("GITHUB_APP_SECRET"),
        github_app_id=os.environ.get("GITHUB_APP_ID"),
        github_app_installation_id=os.environ.get("GITHUB_APP_INSTALLATION_ID"),
        github_app_private_key_secret=os.environ.get("GITHUB_APP_PRIVATE_KEY_SECRET"),
        github_token=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"),
    )


def _gh_cli_token() -> str | None:
    if not shutil.which("gh"):
        return None
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip() or None
    except subprocess.CalledProcessError:
        return None


def _read_secret(secret_id: str, region: str | None) -> str:
    import boto3  # lazy: only needed for live runs

    client = boto3.client("secretsmanager", region_name=region)
    return client.get_secret_value(SecretId=secret_id)["SecretString"]


def resolve_github_token(cfg: Config) -> str:
    """Resolve a usable GitHub bearer token per the priority order (see module doc)."""
    # Preferred: a single JSON secret { app_id, installation_id, private_key }.
    if cfg.github_app_secret:
        from scim_sync.adapters.github_auth import installation_token

        data = json.loads(_read_secret(cfg.github_app_secret, cfg.aws_region))
        return installation_token(
            str(data["app_id"]), str(data["installation_id"]), data["private_key"]
        )

    if cfg.github_app_id and cfg.github_app_installation_id and cfg.github_app_private_key_secret:
        from scim_sync.adapters.github_auth import installation_token

        pem = _read_secret(cfg.github_app_private_key_secret, cfg.aws_region)
        return installation_token(cfg.github_app_id, cfg.github_app_installation_id, pem)

    if cfg.github_token:
        return cfg.github_token.strip()

    cli_token = _gh_cli_token()
    if cli_token:
        return cli_token

    raise RuntimeError(
        "No GitHub auth. Set GITHUB_APP_SECRET (a JSON secret with app_id, "
        "installation_id, private_key), or the discrete GITHUB_APP_* vars, or "
        "GITHUB_TOKEN, or run `gh auth login`."
    )

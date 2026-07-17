"""Tests for GitHub auth resolution priority (no network)."""

from scim_sync import config
from scim_sync.config import Config


def _cfg(**overrides) -> Config:
    base = dict(
        github_org="acme",
        identity_store_id=None,
        aws_region="eu-west-2",
        email_suffix="",
        lookback_minutes=60,
        watermark_file=".watermark.json",
        not_dry_run=False,
        cursor_parameter_name="/scim-sync/audit_cursor",
        max_changes_per_run=50,
        v1_lambda_name=None,
        github_app_secret=None,
        github_app_id=None,
        github_app_installation_id=None,
        github_app_private_key_secret=None,
        github_token=None,
    )
    base.update(overrides)
    return Config(**base)


def test_env_token_used_when_no_app_creds():
    assert config.resolve_github_token(_cfg(github_token="tok123")) == "tok123"


def test_json_secret_path_is_preferred(monkeypatch):
    cfg = _cfg(github_app_secret="my/app/secret", github_token="should-not-be-used")
    payload = '{"app_id": 42, "installation_id": 99, "private_key": "PEM-X"}'
    monkeypatch.setattr(config, "_read_secret", lambda secret_id, region: payload)
    import scim_sync.adapters.github_auth as ga

    monkeypatch.setattr(
        ga, "installation_token", lambda app_id, inst, pem: f"inst:{app_id}:{inst}:{pem}"
    )

    assert config.resolve_github_token(cfg) == "inst:42:99:PEM-X"


def test_app_path_takes_priority_and_mints_installation_token(monkeypatch):
    cfg = _cfg(
        github_app_id="123",
        github_app_installation_id="456",
        github_app_private_key_secret="my/secret",
        github_token="should-not-be-used",
    )
    monkeypatch.setattr(config, "_read_secret", lambda secret_id, region: "PEM-BODY")
    import scim_sync.adapters.github_auth as ga

    monkeypatch.setattr(
        ga, "installation_token", lambda app_id, inst, pem: f"inst:{app_id}:{inst}:{pem}"
    )

    assert config.resolve_github_token(cfg) == "inst:123:456:PEM-BODY"


def test_partial_app_creds_fall_through_to_token(monkeypatch):
    # App id without installation id is not enough -> use the env token.
    cfg = _cfg(github_app_id="123", github_token="tok123")
    assert config.resolve_github_token(cfg) == "tok123"

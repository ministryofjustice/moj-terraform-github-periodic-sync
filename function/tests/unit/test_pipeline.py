"""Tests for the poll -> build-plans pipeline using fake clients (no network/AWS).

Covers the three branches: existing group (membership diff), missing group (new
group create), and a touched team that no longer exists (skipped for the
reconciler).
"""

from scim_sync import pipeline
from scim_sync.config import Config
from scim_sync.logic.watermark import Watermark
from scim_sync.models import GitHubTeam, IdentityGroup


def _cfg(**overrides) -> Config:
    base = dict(
        github_org="acme",
        identity_store_id="d-123",
        aws_region="eu-west-2",
        email_suffix="@example.com",
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
        github_token="t",
    )
    base.update(overrides)
    return Config(**base)


def test_starting_watermark_bootstraps_from_v1(monkeypatch):
    cfg = _cfg(v1_lambda_name="aws-sso-scim-github")
    import scim_sync.adapters.cloudwatch as cw

    monkeypatch.setattr(cw, "last_lambda_execution_ms", lambda name, region: 1699999999000)

    wm = pipeline.starting_watermark(cfg, None)
    assert wm.timestamp_ms == 1699999999000


def test_starting_watermark_falls_back_to_lookback(monkeypatch):
    # v1 lambda name set but no execution found -> lookback window.
    cfg = _cfg(v1_lambda_name="aws-sso-scim-github")
    import scim_sync.adapters.cloudwatch as cw

    monkeypatch.setattr(cw, "last_lambda_execution_ms", lambda name, region: None)

    wm = pipeline.starting_watermark(cfg, None)
    assert wm.timestamp_ms > 0  # a lookback-derived timestamp, not the v1 one


class FakeGitHub:
    def __init__(self, events, teams) -> None:
        self._events = events
        self._teams = teams  # slug -> GitHubTeam | None

    def audit_log(self, phrase: str):
        return self._events

    def get_team(self, slug: str):
        return self._teams.get(slug)


class FakeIdentityStore:
    def __init__(self, groups, users, members) -> None:
        self._groups = groups
        self._users = users
        self._members = members  # group_id -> frozenset[user_id]

    def list_groups(self):
        return self._groups

    def list_users(self):
        return self._users

    def group_member_user_ids(self, group_id: str):
        return self._members.get(group_id, frozenset())


def _event(action, doc_id, ts, team=None, user=None):
    raw = {"action": action, "_document_id": doc_id, "@timestamp": ts}
    if team is not None:
        raw["team"] = f"acme/{team}"
    if user is not None:
        raw["user"] = user
    return raw


def test_existing_group_produces_membership_plan():
    gh = FakeGitHub(
        events=[_event("team.add_member", "d1", 2000, team="platform-team")],
        teams={"platform-team": GitHubTeam(42, "platform-team", "Platform", frozenset({"bob"}))},
    )
    is_client = FakeIdentityStore(
        groups=[IdentityGroup("g1", "platform-team", None)],
        users={"bob@example.com": "user-bob", "carol@example.com": "user-carol"},
        members={"g1": frozenset({"user-carol"})},
    )

    result = pipeline.poll_and_plan(_cfg(), gh, is_client, Watermark(0, None))

    assert result.teams_touched == 1
    assert len(result.plans) == 1
    plan = result.plans[0]
    assert not plan.is_new_group
    assert {c.user_id for c in plan.add} == {"user-bob"}
    assert {c.user_id for c in plan.remove} == {"user-carol"}
    assert result.next_watermark == Watermark(2000, "d1")


def test_missing_group_produces_new_group_plan():
    gh = FakeGitHub(
        events=[_event("team.create", "d1", 3000, team="new-team")],
        teams={"new-team": GitHubTeam(9, "new-team", "New Team", frozenset({"bob"}))},
    )
    is_client = FakeIdentityStore(
        groups=[],  # no group yet
        users={"bob@example.com": "user-bob"},
        members={},
    )

    result = pipeline.poll_and_plan(_cfg(), gh, is_client, Watermark(0, None))

    assert len(result.plans) == 1
    assert result.plans[0].is_new_group
    assert result.plans[0].group_display_name == "new-team"


def test_gone_team_is_skipped():
    gh = FakeGitHub(
        events=[_event("team.destroy", "d1", 4000, team="old-team")],
        teams={"old-team": None},  # team no longer exists
    )
    is_client = FakeIdentityStore(
        groups=[IdentityGroup("g1", "old-team", None)],
        users={},
        members={},
    )

    result = pipeline.poll_and_plan(_cfg(), gh, is_client, Watermark(0, None))

    assert result.plans == []
    assert result.skipped_slugs == ["old-team"]


def test_quiet_poll_touches_no_identity_store():
    # No relevant events -> no plans, watermark unchanged-ish, AWS never queried.
    gh = FakeGitHub(events=[], teams={})

    class Exploding:
        def list_groups(self):
            raise AssertionError("must not touch Identity Store on a quiet poll")

        list_users = list_groups
        group_member_user_ids = list_groups

    result = pipeline.poll_and_plan(_cfg(), gh, Exploding(), Watermark(1000, "d0"))

    assert result.teams_touched == 0
    assert result.plans == []

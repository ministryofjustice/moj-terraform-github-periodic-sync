from contextlib import nullcontext
from types import SimpleNamespace

from scim_sync.handlers import poller
from scim_sync.logic.watermark import Watermark


class FakeCursorStore:
    writes = []

    def __init__(self, *_args) -> None:
        pass

    def get(self):
        return Watermark(1000, "current")

    def put(self, watermark) -> None:
        self.writes.append(watermark)


class FakeApplier:
    def __init__(self, _client, dry_run, log, max_changes) -> None:
        self.dry_run = dry_run

    def apply(self, _plans):
        return SimpleNamespace(as_dict=lambda: {"dry_run": self.dry_run})


def _run_handler(monkeypatch, not_dry_run: bool):
    cfg = SimpleNamespace(
        cursor_parameter_name="/cursor",
        aws_region="eu-west-2",
        github_org="acme",
        not_dry_run=not_dry_run,
        max_changes_per_run=50,
    )
    result = SimpleNamespace(
        skipped_slugs=[],
        plans=[],
        next_watermark=Watermark(2000, "next"),
        audit_events_pulled=1,
        teams_touched=1,
        users_touched=0,
    )
    FakeCursorStore.writes = []
    monkeypatch.setattr(poller.config, "load", lambda: cfg)
    monkeypatch.setattr(poller.config, "resolve_github_token", lambda _cfg: "token")
    monkeypatch.setattr(poller, "SsmCursorStore", FakeCursorStore)
    monkeypatch.setattr(poller.pipeline, "resolve_store_id", lambda _cfg: "d-123")
    monkeypatch.setattr(poller, "IdentityStoreClient", lambda *_args: object())
    monkeypatch.setattr(poller, "GitHubClient", lambda *_args: nullcontext(object()))
    monkeypatch.setattr(poller.pipeline, "poll_and_plan", lambda *_args: result)
    monkeypatch.setattr(poller, "Applier", FakeApplier)

    return poller.handler()


def test_shadow_run_does_not_advance_applied_cursor(monkeypatch):
    summary = _run_handler(monkeypatch, not_dry_run=False)

    assert summary["dry_run"] is True
    assert FakeCursorStore.writes == []


def test_live_run_advances_applied_cursor(monkeypatch):
    summary = _run_handler(monkeypatch, not_dry_run=True)

    assert summary["dry_run"] is False
    assert FakeCursorStore.writes == [Watermark(2000, "next")]
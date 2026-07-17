import json
from pathlib import Path

from scim_sync.logic.audit_events import (
    RELEVANT_ACTIONS,
    AuditEvent,
    parse_entries,
    parse_entry,
    touched_objects,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "audit_log" / "sample.json"


def _load_sample() -> list[dict]:
    return json.loads(FIXTURE.read_text())


def test_parse_entry_extracts_slug_from_org_qualified_team():
    event = parse_entry(
        {
            "action": "team.add_member",
            "_document_id": "d1",
            "@timestamp": 123,
            "user": "bob",
            "team": "ministryofjustice/platform-team",
        }
    )
    assert event == AuditEvent(
        action="team.add_member",
        document_id="d1",
        timestamp_ms=123,
        team_slug="platform-team",
        user_login="bob",
    )


def test_parse_entry_returns_none_without_action_or_id():
    assert parse_entry({"_document_id": "d1"}) is None
    assert parse_entry({"action": "team.add_member"}) is None


def test_parse_entries_drops_unparseable():
    raw = [
        {"action": "team.add_member", "_document_id": "d1", "@timestamp": 1, "team": "o/t"},
        {"garbage": True},
    ]
    parsed = parse_entries(raw)
    assert len(parsed) == 1
    assert parsed[0].document_id == "d1"


def test_touched_objects_collapses_to_sets():
    events = parse_entries(_load_sample())
    touched = touched_objects(events)

    # platform-team mentioned 3x and new-team once -> deduped to two slugs.
    assert touched.team_slugs == frozenset({"platform-team", "new-team"})
    # org.add_member for dave -> one user.
    assert touched.user_logins == frozenset({"dave"})


def test_irrelevant_actions_are_ignored():
    touched = touched_objects(parse_entries([
        {"action": "repo.create", "_document_id": "d", "@timestamp": 1, "repo": "o/r"},
    ]))
    assert touched.team_slugs == frozenset()
    assert touched.user_logins == frozenset()


def test_relevant_actions_cover_team_and_org():
    assert "team.add_member" in RELEVANT_ACTIONS
    assert "org.remove_member" in RELEVANT_ACTIONS
    assert "repo.create" not in RELEVANT_ACTIONS

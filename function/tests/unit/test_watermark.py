from scim_sync.logic.audit_events import AuditEvent
from scim_sync.logic.watermark import (
    Watermark,
    advance,
    is_after,
    new_events,
    query_start_ms,
)


def _event(ts: int, doc: str) -> AuditEvent:
    return AuditEvent(action="team.add_member", document_id=doc, timestamp_ms=ts, team_slug="t")


def test_query_start_applies_overlap_and_floors_at_zero():
    assert query_start_ms(10_000, 2_000) == 8_000
    assert query_start_ms(1_000, 5_000) == 0


def test_is_after_strictly_newer():
    wm = Watermark(timestamp_ms=100, document_id="d1")
    assert is_after(_event(101, "d2"), wm) is True
    assert is_after(_event(99, "d2"), wm) is False


def test_is_after_same_timestamp_uses_document_id():
    wm = Watermark(timestamp_ms=100, document_id="d1")
    assert is_after(_event(100, "d1"), wm) is False  # same event, already done
    assert is_after(_event(100, "d2"), wm) is True  # collision, not yet seen


def test_new_events_drops_overlap_duplicates():
    wm = Watermark(timestamp_ms=100, document_id="d1")
    events = [_event(99, "old"), _event(100, "d1"), _event(101, "new")]
    assert [e.document_id for e in new_events(events, wm)] == ["new"]


def test_advance_picks_newest():
    wm = Watermark(timestamp_ms=100, document_id="d1")
    result = advance(wm, [_event(150, "d2"), _event(120, "d3")])
    assert result == Watermark(150, "d2")


def test_advance_keeps_current_when_no_events():
    wm = Watermark(timestamp_ms=100, document_id="d1")
    assert advance(wm, []) == wm

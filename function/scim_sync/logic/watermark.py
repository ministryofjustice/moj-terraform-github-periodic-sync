"""Watermark logic: where to resume the audit-log query, and how to advance.

Pure functions only. The watermark is anchored on time (the audit-log API has no
"events after id X" query), with the document id kept as a tiebreaker so events
sharing a millisecond aren't skipped or repeated.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from scim_sync.logic.audit_events import AuditEvent


@dataclass(frozen=True, slots=True)
class Watermark:
    """High-water mark of the last processed audit event."""

    timestamp_ms: int
    document_id: str | None = None


def query_start_ms(watermark_ms: int, overlap_ms: int) -> int:
    """Start the ``created:>=`` query slightly before the watermark.

    The overlap re-catches events that landed late or shared a timestamp with the
    last cut; duplicates are dropped later by :func:`is_after` / document id.
    """
    return max(0, watermark_ms - overlap_ms)


def is_after(event: AuditEvent, watermark: Watermark) -> bool:
    """True if ``event`` is strictly newer than the watermark.

    Events at the exact watermark timestamp are considered new only if they are a
    different document — this is what makes the overlap re-fetch idempotent.
    """
    if event.timestamp_ms > watermark.timestamp_ms:
        return True
    if event.timestamp_ms == watermark.timestamp_ms:
        return event.document_id != watermark.document_id
    return False


def new_events(events: Iterable[AuditEvent], watermark: Watermark) -> list[AuditEvent]:
    """Filter to events strictly after the watermark (drops overlap duplicates)."""
    return [event for event in events if is_after(event, watermark)]


def advance(current: Watermark, events: Iterable[AuditEvent]) -> Watermark:
    """Return the newest watermark across ``events``, or ``current`` if none.

    Picks the maximum timestamp; the document id of that event is recorded as the
    tiebreaker for the next run.
    """
    latest = current
    for event in events:
        if event.timestamp_ms > latest.timestamp_ms:
            latest = Watermark(event.timestamp_ms, event.document_id)
    return latest

"""Parse GitHub org audit-log entries and reduce them to *what to reconcile*.

The poller does not act on the delta inside an event. An event only tells us
"this team / this user is worth looking at"; the reconcile step then reads live
state and converges. So this module's whole job is:

    raw audit entries  ->  set of touched team slugs + set of touched user logins

Pure functions only — no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# Audit-log actions we react to. Anything else is ignored.
TEAM_ACTIONS: frozenset[str] = frozenset(
    {
        "team.add_member",
        "team.remove_member",
        "team.create",
        "team.rename",
        "team.destroy",
    }
)
ORG_USER_ACTIONS: frozenset[str] = frozenset(
    {
        "org.add_member",
        "org.remove_member",
    }
)
RELEVANT_ACTIONS: frozenset[str] = TEAM_ACTIONS | ORG_USER_ACTIONS


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """A normalised audit-log entry, keeping only the fields we depend on."""

    action: str
    document_id: str
    timestamp_ms: int
    team_slug: str | None = None
    user_login: str | None = None


@dataclass(frozen=True, slots=True)
class TouchedObjects:
    """The set of teams/users a batch of events says we should reconcile."""

    team_slugs: frozenset[str]
    user_logins: frozenset[str]


def _extract_team_slug(raw: dict) -> str | None:
    """Audit entries carry team as ``"org-name/team-slug"`` (or sometimes bare).

    Return just the slug, or ``None`` if absent.
    """
    team = raw.get("team")
    if not isinstance(team, str) or not team:
        return None
    return team.split("/", 1)[-1]


def parse_entry(raw: dict) -> AuditEvent | None:
    """Normalise one raw audit-log dict into an :class:`AuditEvent`.

    Returns ``None`` for entries with no usable action or id, so callers can
    filter defensively without raising on unexpected shapes.
    """
    action = raw.get("action")
    document_id = raw.get("_document_id")
    if not isinstance(action, str) or not isinstance(document_id, str):
        return None

    timestamp = raw.get("@timestamp")
    timestamp_ms = timestamp if isinstance(timestamp, int) else 0

    user = raw.get("user")
    user_login = user if isinstance(user, str) and user else None

    return AuditEvent(
        action=action,
        document_id=document_id,
        timestamp_ms=timestamp_ms,
        team_slug=_extract_team_slug(raw),
        user_login=user_login,
    )


def parse_entries(raw_entries: Iterable[dict]) -> list[AuditEvent]:
    """Normalise raw entries, dropping unparseable ones."""
    parsed = (parse_entry(raw) for raw in raw_entries)
    return [event for event in parsed if event is not None]


def touched_objects(events: Iterable[AuditEvent]) -> TouchedObjects:
    """Collapse events to the set of teams/users worth reconciling.

    Any mention of a team (membership change, create, rename, destroy) marks the
    whole team for reconciliation. Org membership changes mark the user. Ordering
    and duplicates are irrelevant — we reconcile current state.
    """
    team_slugs: set[str] = set()
    user_logins: set[str] = set()

    for event in events:
        if event.action in TEAM_ACTIONS and event.team_slug:
            team_slugs.add(event.team_slug)
        elif event.action in ORG_USER_ACTIONS and event.user_login:
            user_logins.add(event.user_login)

    return TouchedObjects(
        team_slugs=frozenset(team_slugs),
        user_logins=frozenset(user_logins),
    )

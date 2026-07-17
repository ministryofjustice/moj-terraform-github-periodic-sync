"""Plain data types shared by the pure logic.

These are deliberately simple, immutable, and free of any I/O concern. They
represent *current state already fetched* (by some future adapter) and the
*plan* we would apply — but applying is not implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GitHubTeam:
    """A GitHub team and its current member logins, as read from GitHub."""

    team_id: int
    slug: str
    name: str
    member_logins: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class IdentityGroup:
    """An Identity Store group and its current member user-ids.

    Groups are matched to GitHub teams by ``display_name == team slug`` — the
    slug is the identity the rest of the access process is keyed on. A rename
    therefore reads as a new group rather than being silently followed.
    ``external_id`` is read for information only; it is not used for matching.
    """

    group_id: str
    display_name: str
    external_id: str | None
    member_user_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class MembershipChange:
    """A single proposed membership mutation. Describing only — never applied here.

    ``label`` is a human-friendly name (GitHub login / Identity Store username)
    used only for readable logs; reconciliation keys on ``user_id``.
    """

    group_id: str
    user_id: str
    label: str = ""


@dataclass(frozen=True, slots=True)
class TeamPlan:
    """The proposed changes for one team. Empty add+remove means "no change".

    ``is_new_group`` marks a team that has no Identity Store group yet: the
    poller would create the group (then add ``add`` as its initial members).
    Deleting empty groups / orphaned users is *not* a poller concern — that is a
    nightly reconciler job.
    """

    team_slug: str
    group_id: str
    add: tuple[MembershipChange, ...] = ()
    remove: tuple[MembershipChange, ...] = ()
    group_display_name: str = ""
    is_new_group: bool = False

    @property
    def is_noop(self) -> bool:
        return not self.is_new_group and not self.add and not self.remove

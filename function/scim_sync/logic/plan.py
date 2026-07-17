"""Compose a *reconcile plan* from already-fetched state.

This module is the dry-run output of the whole system: given a GitHub team and
its matching Identity Store group (both already read by some adapter), it
produces a :class:`TeamPlan` describing what *would* change. Nothing here writes
anything anywhere.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from scim_sync.logic.diff import diff_memberships
from scim_sync.models import GitHubTeam, IdentityGroup, MembershipChange, TeamPlan


def _relabel(
    change: MembershipChange, user_id_to_label: Mapping[str, str]
) -> MembershipChange:
    """Attach a human-friendly label to a change, falling back to the user-id."""
    return MembershipChange(
        group_id=change.group_id,
        user_id=change.user_id,
        label=user_id_to_label.get(change.user_id, change.user_id),
    )


def build_team_plan(
    team: GitHubTeam,
    group: IdentityGroup,
    login_to_user_id: Mapping[str, str],
) -> TeamPlan:
    """Build the proposed membership changes for one team.

    ``login_to_user_id`` maps a GitHub login to its Identity Store user-id.
    Logins with no known user-id are skipped (they would be handled by user
    provisioning, a later slice — not by membership reconciliation).
    """
    desired_user_ids = frozenset(
        login_to_user_id[login]
        for login in team.member_logins
        if login in login_to_user_id
    )
    add, remove = diff_memberships(desired_user_ids, group.member_user_ids, group.group_id)
    user_id_to_label = {uid: login for login, uid in login_to_user_id.items()}
    return TeamPlan(
        team_slug=team.slug,
        group_id=group.group_id,
        add=tuple(_relabel(c, user_id_to_label) for c in add),
        remove=tuple(_relabel(c, user_id_to_label) for c in remove),
        group_display_name=group.display_name,
    )


def build_new_group_plan(
    team: GitHubTeam,
    login_to_user_id: Mapping[str, str],
) -> TeamPlan:
    """Build the plan for a team that has no Identity Store group yet.

    The poller would create the group immediately and seed it with the team's
    members. ``group_id`` is unknown until creation, so it is left blank.
    """
    add = tuple(
        MembershipChange(group_id="", user_id=login_to_user_id[login], label=login)
        for login in sorted(team.member_logins)
        if login in login_to_user_id
    )
    return TeamPlan(
        team_slug=team.slug,
        group_id="",
        add=add,
        group_display_name=team.slug,
        is_new_group=True,
    )


def render_plan(plans: Iterable[TeamPlan]) -> str:
    """Render plans as human-readable dry-run text for logging.

    Names (logins / group display names) are shown rather than UUIDs. No-op
    teams are summarised, not listed line by line, to keep output useful.
    """
    lines: list[str] = []
    created = 0
    changed = 0
    noops = 0

    for plan in plans:
        if plan.is_noop:
            noops += 1
            continue
        if plan.is_new_group:
            created += 1
            lines.append(
                f"team '{plan.team_slug}' -> CREATE group '{plan.group_display_name}':"
            )
        else:
            changed += 1
            group_label = plan.group_display_name or plan.group_id
            lines.append(f"team '{plan.team_slug}' (group '{group_label}'):")
        for change in plan.add:
            lines.append(f"  + add {change.label}")
        for change in plan.remove:
            lines.append(f"  - remove {change.label}")

    header = (
        f"DRY RUN: {created} group(s) to create, "
        f"{changed} team(s) to update, {noops} unchanged"
    )
    if not lines:
        return header
    return header + "\n" + "\n".join(lines)

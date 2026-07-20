"""Pure membership diff: given desired vs actual members, what changes?

This is the testable heart of the reconciler. It produces *descriptions* of
changes (add/remove). It never applies them.
"""

from __future__ import annotations

from scim_sync.models import MembershipChange


def diff_memberships(
    desired_user_ids: frozenset[str],
    actual_user_ids: frozenset[str],
    group_id: str,
) -> tuple[tuple[MembershipChange, ...], tuple[MembershipChange, ...]]:
    """Return ``(add, remove)`` membership changes to converge actual -> desired.

    - ``add``: users desired but not currently members.
    - ``remove``: users currently members but no longer desired.

    Identical inputs yield two empty tuples (a no-op), which is what makes
    re-reconciling a team harmless.
    """
    add = tuple(
        MembershipChange(group_id=group_id, user_id=user_id)
        for user_id in sorted(desired_user_ids - actual_user_ids)
    )
    remove = tuple(
        MembershipChange(group_id=group_id, user_id=user_id)
        for user_id in sorted(actual_user_ids - desired_user_ids)
    )
    return add, remove

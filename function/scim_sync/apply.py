"""Apply reconcile plans to the Identity Store, gated by dry-run.

This is the only place that turns a :class:`~scim_sync.models.TeamPlan` into real
writes. It performs exactly the three permitted verbs — create group, add member,
remove member — and nothing destructive (no group/user deletion; that is the
nightly reconciler's job).

When ``dry_run`` is true (the default; production sets ``NOT_DRY_RUN=true`` to go
live) it logs what *would* happen and calls no write method, so the same code path
is exercised in shadow mode as in production.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from scim_sync.adapters.identity_store import IdentityStoreClient
from scim_sync.models import TeamPlan


class BlastRadiusError(RuntimeError):
    """Raised when a single run would make more changes than the safety cap allows.

    Guards against a runaway run — e.g. a transient GitHub response that returns an
    empty member list, which would otherwise diff to "remove everyone". When this
    fires, no writes have been performed and the watermark is not advanced, so the
    failed invocation alarms and a human can investigate before anything mutates.
    """


@dataclass
class ApplyResult:
    groups_created: int = 0
    members_added: int = 0
    members_removed: int = 0
    dry_run: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "groups_created": self.groups_created,
            "members_added": self.members_added,
            "members_removed": self.members_removed,
            "dry_run": self.dry_run,
        }


def _default_log(message: str) -> None:
    print(message, file=sys.stderr)


def _plan_change_count(plan: TeamPlan) -> int:
    return (1 if plan.is_new_group else 0) + len(plan.add) + len(plan.remove)


class Applier:
    """Applies plans. Writes only when ``dry_run`` is false."""

    def __init__(
        self,
        is_client: IdentityStoreClient,
        dry_run: bool = True,
        log: Callable[[str], None] = _default_log,
        max_changes: int | None = None,
    ) -> None:
        self._is = is_client
        self._dry_run = dry_run
        self._log = log
        self._max_changes = max_changes

    def _prefix(self) -> str:
        return "WOULD" if self._dry_run else "DID"

    def apply(self, plans: Iterable[TeamPlan]) -> ApplyResult:
        plans = [p for p in plans if not p.is_noop]

        # Blast-radius guard: count intended changes before touching anything.
        total = sum(_plan_change_count(p) for p in plans)
        if self._max_changes is not None and total > self._max_changes:
            self._log(
                f"BLAST-RADIUS: {total} changes exceeds cap of {self._max_changes} "
                f"across {len(plans)} team(s) — refusing to proceed."
            )
            if not self._dry_run:
                raise BlastRadiusError(
                    f"{total} changes exceeds MAX_CHANGES_PER_RUN={self._max_changes}"
                )

        result = ApplyResult(dry_run=self._dry_run)
        for plan in plans:
            group_id = self._ensure_group(plan, result)
            for change in plan.add:
                if not self._dry_run:
                    self._is.add_member(group_id, change.user_id)
                self._log(f"  {self._prefix()} add {change.label} -> '{plan.team_slug}'")
                result.members_added += 1
            for change in plan.remove:
                if not self._dry_run:
                    self._is.remove_member(group_id, change.user_id)
                self._log(f"  {self._prefix()} remove {change.label} <- '{plan.team_slug}'")
                result.members_removed += 1
        return result

    def _ensure_group(self, plan: TeamPlan, result: ApplyResult) -> str:
        """Return the group id to write members into, creating it if new.

        In dry-run a brand-new group has no real id yet, so an empty string is
        returned; it is never used because the membership writes below are guarded
        by ``not self._dry_run``.
        """
        if not plan.is_new_group:
            return plan.group_id
        self._log(
            f"team '{plan.team_slug}' -> {self._prefix()} CREATE group "
            f"'{plan.group_display_name}'"
        )
        result.groups_created += 1
        if self._dry_run:
            return ""
        return self._is.create_group(plan.group_display_name)

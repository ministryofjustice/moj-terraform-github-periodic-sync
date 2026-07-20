"""Shared poll -> build-plans pipeline.

Both the local dry-run CLI (:mod:`scim_sync.dry_run`) and the Lambda handler
(:mod:`scim_sync.handlers.poller`) need the same sequence: query the audit log
from the watermark, collapse to touched teams, and produce a :class:`TeamPlan`
per team. That logic lives here once so the two entry points cannot drift.

This module orchestrates already-constructed clients; it performs no I/O of its
own and never writes anything (applying plans is :mod:`scim_sync.apply`'s job).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from scim_sync import config
from scim_sync.adapters.github_client import GitHubClient
from scim_sync.adapters.identity_store import IdentityStoreClient, discover_identity_store_id
from scim_sync.logic import audit_events, watermark
from scim_sync.logic.audit_events import RELEVANT_ACTIONS
from scim_sync.logic.plan import build_new_group_plan, build_team_plan
from scim_sync.logic.watermark import Watermark
from scim_sync.models import IdentityGroup, TeamPlan

# Re-query slightly before the watermark so late-landing events are not missed;
# overlap duplicates are dropped by watermark.new_events.
_OVERLAP_MS = 2 * 60_000


@dataclass
class PlanResult:
    """Everything a caller needs after a poll: the plans and the next watermark."""

    audit_events_pulled: int
    teams_touched: int
    users_touched: int
    plans: list[TeamPlan]
    skipped_slugs: list[str]
    next_watermark: Watermark


def audit_phrase(start_ms: int) -> str:
    """Build the open-ended ``created:>=`` phrase plus the actions we care about."""
    start_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_ms / 1000))
    actions = " ".join(f"action:{a}" for a in sorted(RELEVANT_ACTIONS))
    return f"created:>={start_iso} {actions}"


def resolve_store_id(cfg: config.Config) -> str:
    """Use the configured Identity Store id, or discover it from the SSO instance."""
    if cfg.identity_store_id:
        return cfg.identity_store_id
    return discover_identity_store_id(cfg.aws_region)


def starting_watermark(cfg: config.Config, current: Watermark | None) -> Watermark:
    """Resolve the watermark to resume from.

    Priority when there is no existing cursor (first run):
      1. The v1 Lambda's last execution time, if ``v1_lambda_name`` is set — so the
         cutover leaves no gap. (One-time bootstrap; the event watermark takes over
         thereafter.)
      2. A ``lookback_minutes`` window before now.
    """
    if current is not None:
        return current

    if cfg.v1_lambda_name:
        from scim_sync.adapters.cloudwatch import last_lambda_execution_ms

        last_ms = last_lambda_execution_ms(cfg.v1_lambda_name, cfg.aws_region)
        if last_ms is not None:
            return Watermark(timestamp_ms=last_ms, document_id=None)

    start_ms = int(time.time() * 1000) - cfg.lookback_minutes * 60_000
    return Watermark(timestamp_ms=start_ms, document_id=None)


def _login_to_user_id(users: dict[str, str], email_suffix: str) -> dict[str, str]:
    """Map GitHub login -> Identity Store user-id by stripping the email suffix."""
    return {
        uname.replace(email_suffix, ""): uid
        for uname, uid in users.items()
    }


def poll_and_plan(
    cfg: config.Config,
    gh: GitHubClient,
    is_client: IdentityStoreClient,
    current_wm: Watermark | None,
) -> PlanResult:
    """Poll the audit log from ``current_wm`` and build one plan per touched team.

    The Identity Store is only read when at least one team was actually touched,
    so a quiet poll costs nothing on the AWS side. Read-only: returns plans, never
    applies them.
    """
    wm = starting_watermark(cfg, current_wm)
    start_ms = watermark.query_start_ms(wm.timestamp_ms, _OVERLAP_MS)

    raw = gh.audit_log(audit_phrase(start_ms))
    parsed = audit_events.parse_entries(raw)
    fresh = watermark.new_events(parsed, wm)
    touched = audit_events.touched_objects(fresh)

    plans: list[TeamPlan] = []
    skipped: list[str] = []

    if touched.team_slugs:
        groups = is_client.list_groups()
        users = is_client.list_users()
        by_name = {g.display_name: g for g in groups if g.display_name}
        login_to_user_id = _login_to_user_id(users, cfg.email_suffix)

        for slug in sorted(touched.team_slugs):
            team = gh.get_team(slug)
            if team is None:
                # Team gone (destroy/rename away): deletion is the reconciler's job.
                skipped.append(slug)
                continue
            # Identity is the slug == group DisplayName. A renamed team reads as a
            # new group; the old one is left to the nightly reconciler.
            group = by_name.get(team.slug)
            if group is None:
                plans.append(build_new_group_plan(team, login_to_user_id))
                continue
            members = is_client.group_member_user_ids(group.group_id)
            group = IdentityGroup(
                group_id=group.group_id,
                display_name=group.display_name,
                external_id=group.external_id,
                member_user_ids=members,
            )
            plans.append(build_team_plan(team, group, login_to_user_id))

    return PlanResult(
        audit_events_pulled=len(parsed),
        teams_touched=len(touched.team_slugs),
        users_touched=len(touched.user_logins),
        plans=plans,
        skipped_slugs=skipped,
        next_watermark=watermark.advance(wm, fresh),
    )

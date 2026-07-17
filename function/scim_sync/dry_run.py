"""Dry-run runner: poll the real org audit log, reconcile against the real
Identity Center, and print what *would* change — without writing anything.

It shares the exact poll -> build-plans logic the Lambda uses
(:mod:`scim_sync.pipeline`); the only difference is the cursor lives in a local
file and the applier is forced into dry-run. It also reports efficiency vs a full
reconcile.

Run with:  python -m scim_sync.dry_run
Optionally add --baseline to *estimate* a full-reconcile read pass for comparison
(it counts teams + groups cheaply and projects the per-entity call cost, rather
than actually fetching every team's and group's members).
"""

from __future__ import annotations

import argparse
import sys

from scim_sync import config, pipeline
from scim_sync.adapters.github_client import GitHubClient
from scim_sync.adapters.identity_store import IdentityStoreClient
from scim_sync.adapters.metrics import CallCounter
from scim_sync.adapters.watermark_store import FileWatermarkStore
from scim_sync.apply import Applier
from scim_sync.logic.plan import render_plan


def _estimate_full_reconcile(cfg: config.Config, github_token: str) -> tuple[int, int, int, int]:
    """*Estimate* the read cost a full reconcile (v1-style) would incur.

    Only the cheap listing calls are made (list teams, list groups, list users);
    the expensive per-team and per-group member fetches are *not* executed.
    Instead we project them as one call each (the common single-page case), which
    is a lower bound — large teams/groups would page and cost more.

    Returns (team_count, group_count, est_github_calls, est_identity_calls).
    Read-only.
    """
    gh_counter = CallCounter()
    is_counter = CallCounter()
    with GitHubClient(cfg.github_org, github_token, gh_counter) as gh:
        slugs = gh.list_team_slugs()
        is_client = IdentityStoreClient(
            pipeline.resolve_store_id(cfg), cfg.aws_region, is_counter
        )
        groups = is_client.list_groups()
        is_client.list_users()

    team_count = len(slugs)
    group_count = len(groups)
    # Listing cost actually incurred + one projected member fetch per team/group.
    est_github = gh_counter.total() + team_count
    est_identity = is_counter.total() + group_count
    return team_count, group_count, est_github, est_identity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dry-run audit-log poller (no writes).")
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Also estimate a full-reconcile read pass for comparison (cheap; no member fetches).",
    )
    args = parser.parse_args(argv)

    cfg = config.load()
    gh_counter = CallCounter()
    is_counter = CallCounter()

    print(f"== DRY RUN (no writes) :: org='{cfg.github_org}' ==")

    store = FileWatermarkStore(cfg.watermark_file)
    current_wm = store.get()
    if current_wm is None:
        print(f"No watermark file; starting from {cfg.lookback_minutes} min ago.", file=sys.stderr)

    store_id = pipeline.resolve_store_id(cfg)
    print(f"Identity Store id: {store_id}", file=sys.stderr)
    is_client = IdentityStoreClient(store_id, cfg.aws_region, is_counter)

    github_token = config.resolve_github_token(cfg)
    with GitHubClient(cfg.github_org, github_token, gh_counter) as gh:
        result = pipeline.poll_and_plan(cfg, gh, is_client, current_wm)

    for slug in result.skipped_slugs:
        print(
            f"  - team '{slug}' no longer exists -> skip (reconciler handles deletion)",
            file=sys.stderr,
        )

    print()
    print(render_plan(result.plans))
    print()
    # Exercise the same apply path production uses, but forced into dry-run.
    Applier(is_client, dry_run=True).apply(result.plans)

    print()
    print("---- this run (delta / audit-log poll) ----")
    print(f"audit events pulled : {result.audit_events_pulled}")
    print(f"teams to reconcile  : {result.teams_touched}")
    print(f"users touched       : {result.users_touched}")
    print(f"GitHub API calls    : {gh_counter.total()}  {gh_counter.as_dict()}")
    print(f"Identity API calls  : {is_counter.total()}  {is_counter.as_dict()}")
    delta_total = gh_counter.total() + is_counter.total()

    if args.baseline:
        print()
        print("Estimating full-reconcile baseline (cheap: counts only, no member fetches)...")
        team_count, group_count, gh_full, is_full = _estimate_full_reconcile(cfg, github_token)
        full_total = gh_full + is_full
        print("---- full reconcile (v1-style, every run) — ESTIMATED ----")
        print(f"teams in org        : {team_count}")
        print(f"groups in IC        : {group_count}")
        print(f"GitHub API calls    : ~{gh_full}  (list + 1/team)")
        print(f"Identity API calls  : ~{is_full}  (list groups+users + 1/group)")
        print("note: estimate assumes single-page member fetches (lower bound).")
        print()
        print("---- efficiency ----")
        print(f"teams reconciled    : {result.teams_touched} / {team_count}")
        if full_total:
            saved = 100 * (1 - delta_total / full_total)
            print(f"API calls           : {delta_total} (delta) vs ~{full_total} (full, est.)")
            print(f"reduction           : ~{saved:.1f}% fewer API calls this cycle")
    else:
        print()
        print("Run again with --baseline to compare against a full reconcile.")

    # Absolute last write: only advance the watermark once every preceding step
    # has completed without error. In production this is the SSM cursor update.
    store.put(result.next_watermark)
    print(f"watermark advanced to {result.next_watermark}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

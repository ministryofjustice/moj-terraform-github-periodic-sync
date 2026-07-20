"""AWS Lambda entrypoint: scheduled audit-log poll -> reconcile.

Thin by design. It wires the shared pipeline (:mod:`scim_sync.pipeline`) to the
production cursor (SSM) and the applier (:mod:`scim_sync.apply`), then advances
the cursor **last** so a mid-run failure simply re-covers the same window on the
next schedule.

Writes happen only when ``NOT_DRY_RUN=true``; otherwise the function runs in
shadow mode, logging the diff it *would* apply. Invoked on an EventBridge
schedule; the ``event``/``context`` arguments are unused.
"""

from __future__ import annotations

import json
import logging

from scim_sync import config, pipeline
from scim_sync.adapters.cursor_store import SsmCursorStore
from scim_sync.adapters.github_client import GitHubClient
from scim_sync.adapters.identity_store import IdentityStoreClient
from scim_sync.adapters.metrics import CallCounter
from scim_sync.apply import Applier

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: object = None, context: object = None) -> dict:
    cfg = config.load()
    gh_counter = CallCounter()
    is_counter = CallCounter()

    store = SsmCursorStore(cfg.cursor_parameter_name, cfg.aws_region)
    current_wm = store.get()

    store_id = pipeline.resolve_store_id(cfg)
    is_client = IdentityStoreClient(store_id, cfg.aws_region, is_counter)

    github_token = config.resolve_github_token(cfg)
    with GitHubClient(cfg.github_org, github_token, gh_counter) as gh:
        plan_result = pipeline.poll_and_plan(cfg, gh, is_client, current_wm)

    for slug in plan_result.skipped_slugs:
        logger.info("team '%s' no longer exists -> skipped (reconciler handles deletion)", slug)

    applier = Applier(
        is_client,
        dry_run=not cfg.not_dry_run,
        log=logger.info,
        max_changes=cfg.max_changes_per_run,
    )
    apply_result = applier.apply(plan_result.plans)

    # Absolute last write: advance the cursor only after every preceding step
    # succeeded. On failure it stays put and the next poll re-covers the window.
    store.put(plan_result.next_watermark)

    summary = {
        "dry_run": not cfg.not_dry_run,
        "audit_events_pulled": plan_result.audit_events_pulled,
        "teams_touched": plan_result.teams_touched,
        "users_touched": plan_result.users_touched,
        "skipped_teams": len(plan_result.skipped_slugs),
        **apply_result.as_dict(),
        "github_calls": gh_counter.total(),
        "identity_calls": is_counter.total(),
        "watermark": {
            "timestamp_ms": plan_result.next_watermark.timestamp_ms,
            "document_id": plan_result.next_watermark.document_id,
        },
    }
    logger.info("poll complete: %s", json.dumps(summary))
    return summary

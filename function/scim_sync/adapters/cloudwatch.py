"""Look up a Lambda's last execution time from its CloudWatch Logs.

Used once, on the poller's very first run, to seed the initial audit-log window
from where the v1 Lambda last ran — so no changes are missed in the gap between
v1 stopping and v2 starting. After that the event watermark takes over.

``boto3`` is imported lazily; a client may be injected for testing.
"""

from __future__ import annotations

from scim_sync.adapters.aws_errors import error_code


def last_lambda_execution_ms(
    function_name: str, region: str | None = None, client=None
) -> int | None:
    """Return the last-event timestamp (ms) of the function's newest log stream.

    Approximates the last execution time. Returns ``None`` if the log group or a
    stream doesn't exist (e.g. the function never ran), so the caller can fall
    back to the configured lookback.
    """
    if client is None:
        import boto3  # lazy: only needed for live runs

        client = boto3.client("logs", region_name=region)

    log_group = f"/aws/lambda/{function_name}"
    try:
        response = client.describe_log_streams(
            logGroupName=log_group,
            orderBy="LastEventTime",
            descending=True,
            limit=1,
        )
    except Exception as exc:
        if error_code(exc) == "ResourceNotFoundException":
            return None
        raise

    streams = response.get("logStreams", [])
    if not streams:
        return None
    ts = streams[0].get("lastEventTimestamp") or streams[0].get("lastIngestionTime")
    return int(ts) if ts else None

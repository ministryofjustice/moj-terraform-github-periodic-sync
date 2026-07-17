"""SSM-backed watermark (audit-log cursor) store for production.

Mirrors :class:`~scim_sync.adapters.watermark_store.FileWatermarkStore`'s
``get()``/``put()`` shape so the handler can swap the local file for the real
cursor with no logic change. The watermark is stored as small JSON in a single
SSM Parameter Store ``String`` parameter (versioned and free; no DynamoDB).

``boto3`` is imported lazily so the pure logic core and its tests never require
it; a client may also be injected for testing. AWS error codes are read by
duck-typing (see :mod:`scim_sync.adapters.aws_errors`), so no ``botocore`` import
is needed at all.
"""

from __future__ import annotations

import json

from scim_sync.adapters.aws_errors import error_code
from scim_sync.logic.watermark import Watermark


class SsmCursorStore:
    def __init__(self, parameter_name: str, region: str | None = None, client=None) -> None:
        self._name = parameter_name
        if client is not None:
            self._client = client
        else:
            import boto3  # lazy: only needed for live runs

            self._client = boto3.client("ssm", region_name=region)

    def get(self) -> Watermark | None:
        try:
            response = self._client.get_parameter(Name=self._name)
        except Exception as exc:
            if error_code(exc) == "ParameterNotFound":
                return None  # first run — no cursor yet
            raise
        try:
            data = json.loads(response["Parameter"]["Value"])
            return Watermark(
                timestamp_ms=int(data["timestamp_ms"]),
                document_id=data.get("document_id"),
            )
        except (ValueError, KeyError, TypeError):
            # Terraform seeds the parameter with a placeholder before the poller
            # has written a real cursor; treat anything unparseable as first-run.
            return None

    def put(self, watermark: Watermark) -> None:
        self._client.put_parameter(
            Name=self._name,
            Type="String",
            Overwrite=True,
            Value=json.dumps(
                {
                    "timestamp_ms": watermark.timestamp_ms,
                    "document_id": watermark.document_id,
                }
            ),
        )

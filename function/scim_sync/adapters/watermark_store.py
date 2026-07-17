"""File-backed watermark store (a stand-in for SSM during local dry runs).

Same get/put shape an SSM-backed store would have, so swapping it later is a
one-line change. Stores the watermark as small JSON on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

from scim_sync.logic.watermark import Watermark


class FileWatermarkStore:
    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def get(self) -> Watermark | None:
        if not self._path.exists():
            return None
        data = json.loads(self._path.read_text())
        return Watermark(
            timestamp_ms=int(data["timestamp_ms"]),
            document_id=data.get("document_id"),
        )

    def put(self, watermark: Watermark) -> None:
        self._path.write_text(
            json.dumps(
                {"timestamp_ms": watermark.timestamp_ms, "document_id": watermark.document_id},
                indent=2,
            )
        )

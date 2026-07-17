"""A tiny shared API-call counter so the dry run can report efficiency.

Each read-only client increments a labelled counter per HTTP/SDK call. The runner
prints these so we can compare the delta approach against a full reconcile.
"""

from __future__ import annotations

from collections import Counter


class CallCounter:
    """Counts API calls by label. Not thread-safe; fine for a single poll."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()

    def incr(self, label: str, n: int = 1) -> None:
        self._counts[label] += n

    def total(self) -> int:
        return sum(self._counts.values())

    def as_dict(self) -> dict[str, int]:
        return dict(self._counts)

"""Duck-typed AWS error inspection.

Avoids importing ``botocore`` just to read an error code, so the adapters stay
unit-testable with a fake client that raises an exception carrying a ``response``
dict in the same shape boto3 uses.
"""

from __future__ import annotations


def error_code(exc: BaseException) -> str | None:
    """Return the AWS error code from a boto3-style exception, or ``None``."""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if isinstance(code, str):
            return code
    return None

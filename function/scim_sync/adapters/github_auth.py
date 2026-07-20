"""GitHub App authentication: mint a short-lived installation access token.

The poller authenticates as a GitHub App (not a PAT). We build a signed JWT from
the App's private key, then exchange it for an installation token scoped to the
org. Installation tokens last ~1 hour; a poll runs in seconds, so we mint one per
invocation rather than caching.

``jwt`` and ``httpx`` are imported lazily so the pure logic core and its tests
never require them.
"""

from __future__ import annotations

import time


def _app_jwt(app_id: str, private_key_pem: str) -> str:
    import jwt  # PyJWT (+ cryptography for RS256)

    now = int(time.time())
    payload = {
        "iat": now - 60,   # allow for small clock drift
        "exp": now + 540,  # max 10 min; stay well under
        "iss": str(app_id),
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


def installation_token(app_id: str, installation_id: str, private_key_pem: str) -> str:
    """Return an installation access token for the App on this installation."""
    import httpx

    app_jwt = _app_jwt(app_id, private_key_pem)
    response = httpx.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()["token"]

"""Read-only GitHub REST client (audit log + team members + team list).

No write methods exist. ``httpx`` is imported lazily so the pure logic core and
its tests never require it.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from urllib.parse import quote

from scim_sync.adapters.metrics import CallCounter
from scim_sync.models import GitHubTeam

_API = "https://api.github.com"
_PER_PAGE = 100


class GitHubClient:
    def __init__(self, org: str, token: str, counter: CallCounter) -> None:
        import httpx  # lazy: only needed for live runs

        self._org = org
        self._counter = counter
        self._http = httpx.Client(
            base_url=_API,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _get(self, path: str, params: dict | None = None):
        import httpx

        for attempt in range(5):
            response = self._http.get(path, params=params)
            self._counter.incr("github.get")
            # Respect primary/secondary rate limits politely.
            if response.status_code in (403, 429):
                retry_after = response.headers.get("retry-after")
                remaining = response.headers.get("x-ratelimit-remaining")
                if retry_after:
                    time.sleep(min(float(retry_after), 60))
                    continue
                if remaining == "0":
                    reset = float(response.headers.get("x-ratelimit-reset", "0"))
                    wait = max(0.0, reset - time.time()) + 1
                    time.sleep(min(wait, 60))
                    continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                if attempt < 4 and response.status_code >= 500:
                    time.sleep(2**attempt)
                    continue
                raise
            return response
        raise RuntimeError(f"GitHub GET {path} failed after retries")

    def _paginate(self, path: str, params: dict | None = None) -> Iterator[dict]:
        params = {**(params or {}), "per_page": _PER_PAGE}
        url: str | None = path
        next_params: dict | None = params
        while url:
            response = self._get(url, next_params)
            body = response.json()
            if isinstance(body, list):
                yield from body
            else:
                yield body
            link = response.links.get("next")
            if link:
                url = link["url"]
                next_params = None  # the next link already carries query params
            else:
                url = None

    def audit_log(self, phrase: str) -> list[dict]:
        """Return audit-log entries matching ``phrase`` (oldest first)."""
        return list(
            self._paginate(
                f"/orgs/{self._org}/audit-log",
                {"phrase": phrase, "order": "asc", "include": "web"},
            )
        )

    def team_member_logins(self, team_slug: str) -> list[str]:
        """Return current member logins for one team."""
        slug = quote(team_slug, safe="")
        members = self._paginate(f"/orgs/{self._org}/teams/{slug}/members")
        return [m["login"] for m in members if "login" in m]

    def get_team(self, team_slug: str) -> GitHubTeam | None:
        """Fetch a team's current member logins (and metadata) by slug.

        Returns ``None`` if the team no longer exists (e.g. a ``team.destroy`` or
        a rename that moved the slug away): deletion is the reconciler's job, so
        the poller just skips it. Identity is the **slug** — the same key access
        is managed on — not the team id, so a rename reads as "new slug appeared,
        old slug gone", which is exactly the intended behaviour.
        """
        import httpx

        try:
            response = self._get(f"/orgs/{self._org}/teams/{quote(team_slug, safe='')}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        data = response.json()
        member_logins = frozenset(self.team_member_logins(team_slug))
        return GitHubTeam(
            team_id=data["id"],
            slug=data.get("slug", team_slug),
            name=data.get("name", team_slug),
            member_logins=member_logins,
        )

    def list_team_slugs(self) -> list[str]:
        """Return all team slugs in the org (used only for the full-reconcile baseline)."""
        teams = self._paginate(f"/orgs/{self._org}/teams")
        return [t["slug"] for t in teams if "slug" in t]

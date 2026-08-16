"""GitHub REST client.

Only repository listing and metadata go through this client. Commit history
and file contents come from clones, because a clone is one operation over git
transport and is not billed against the REST hourly quota.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Self

import httpx

from veriquill.config import Settings
from veriquill.github.cache import ResponseCache

_NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')


class MissingTokenError(RuntimeError):
    """Raised when no GitHub token is configured.

    Unauthenticated REST allows 60 requests per hour, which cannot complete a
    real analysis. Veriquill refuses to start rather than degrade silently.
    """


class RateLimitExhausted(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._transport = transport
        self._cache = ResponseCache(settings.cache_dir)
        self._client: httpx.AsyncClient | None = None
        self._pending_next: str | None = None
        self.remaining: int | None = None
        self.reset_at: float | None = None

    async def __aenter__(self) -> Self:
        token = self._settings.github_token.get_secret_value()
        if not token:
            raise MissingTokenError(
                "VERIQUILL_GITHUB_TOKEN is not set. Unauthenticated GitHub REST "
                "allows only 60 requests per hour, which is not enough to "
                "analyse an account."
            )
        self._client = httpx.AsyncClient(
            base_url=self._settings.api_base_url,
            transport=self._transport,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "veriquill",
            },
            timeout=30.0,
        )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _absolute(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self._settings.api_base_url}{path}"

    def _record_quota(self, response: httpx.Response) -> None:
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining is not None:
            self.remaining = int(remaining)
        reset = response.headers.get("X-RateLimit-Reset")
        if reset is not None:
            self.reset_at = float(reset)

    @staticmethod
    def _parse_next_link(response: httpx.Response) -> str | None:
        link = response.headers.get("Link")
        if not link:
            return None
        match = _NEXT_LINK.search(link)
        return match.group(1) if match else None

    async def _wait_if_quota_low(self) -> None:
        if self.remaining is None or self.reset_at is None:
            return
        if self.remaining > self._settings.rate_limit_floor:
            return
        delay = self.reset_at - time.time() + 1.0
        if delay > 0:
            await asyncio.sleep(delay)
        self.remaining = None

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        assert self._client is not None, "GitHubClient must be used as a context manager"
        url = self._absolute(path)
        cached = self._cache.get(url)
        headers = {"If-None-Match": cached.etag} if cached else {}

        for _attempt in range(self._settings.max_retry_attempts):
            await self._wait_if_quota_low()
            response = await self._client.get(path, params=params, headers=headers)
            self._record_quota(response)

            if response.status_code == 304 and cached is not None:
                self._pending_next = self._parse_next_link(response)
                return cached.payload

            if response.status_code in (403, 429):
                retry_after = response.headers.get("Retry-After")
                if retry_after is not None:
                    await asyncio.sleep(float(retry_after))
                    continue
                if self.remaining == 0:
                    raise RateLimitExhausted(
                        "GitHub primary rate limit is exhausted; retry after reset."
                    )

            response.raise_for_status()
            payload = response.json()
            etag = response.headers.get("ETag")
            if etag:
                self._cache.set(url, etag, payload)
            self._pending_next = self._parse_next_link(response)
            return payload

        raise RateLimitExhausted(
            f"gave up on {path} after {self._settings.max_retry_attempts} attempts"
        )

    async def paginate(self, path: str, params: dict[str, Any] | None = None) -> list[dict]:
        assert self._client is not None, "GitHubClient must be used as a context manager"
        merged = {"per_page": 100, **(params or {})}
        items: list[dict] = []
        next_url: str | None = path
        use_params: dict[str, Any] | None = merged

        while next_url is not None:
            page = await self.get_json(next_url, params=use_params)
            items.extend(page)
            next_url = self._pending_next
            use_params = None

        return items

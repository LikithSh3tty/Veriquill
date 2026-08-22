"""Caps that keep an unauthenticated API from being an open cost.

There is no authentication in front of this server, which means every endpoint
is reachable by anyone who can reach the host. That is a deployment decision
recorded elsewhere, but it makes two things true here: nothing may be read into
memory before its size is known, and no caller may start unbounded work.

None of this is a substitute for authentication. It is the floor beneath it: a
misconfigured deployment should cost a 413 or a 429, not the process.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from fastapi import HTTPException, Request, UploadFile
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Read size, in bytes, for bounded upload reads. Small enough that a refusal
# costs one chunk of memory, large enough not to thrash on a legitimate file.
CHUNK_BYTES = 64 * 1024


class LimitExceeded(Exception):
    """Raised when a caller asked for more than the server will give."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


async def read_capped(upload: UploadFile, limit: int, label: str) -> bytes:
    """Read an upload, refusing it the moment it exceeds `limit`.

    `UploadFile.read()` with no argument buffers the whole body first and checks
    the size afterwards, which makes the size check useless as a defence: the
    memory is already spent by the time the limit is consulted. Reading in
    chunks means an oversized upload costs one chunk and a refusal.
    """
    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await upload.read(CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise LimitExceeded(
                413,
                f"{label} is larger than the {limit // 1024} KB limit",
            )
        chunks.append(chunk)

    return b"".join(chunks)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Refuse an oversized request before anything reads it.

    A declared Content-Length is refused outright. A chunked request declares
    nothing, so the body is metered as it streams and cut off at the same limit
    - otherwise the cap is advisory and a client that omits the header walks
    straight past it.
    """

    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                return JSONResponse({"detail": "malformed Content-Length"}, status_code=400)
            if length > self.max_bytes:
                return JSONResponse(
                    {"detail": f"request body exceeds {self.max_bytes // 1024} KB"},
                    status_code=413,
                )
        else:
            over = await self._body_exceeds_limit(request)
            if over:
                return JSONResponse(
                    {"detail": f"request body exceeds {self.max_bytes // 1024} KB"},
                    status_code=413,
                )

        return await call_next(request)

    async def _body_exceeds_limit(self, request: Request) -> bool:
        """Meter an undeclared body, and hand the bytes back to the handler.

        The stream can only be consumed once, so what is read here is cached on
        the request for the route to read again. That is the cost of metering a
        chunked body, and it is bounded by the same limit.
        """
        total = 0
        chunks: list[bytes] = []

        async for chunk in request.stream():
            total += len(chunk)
            if total > self.max_bytes:
                return True
            chunks.append(chunk)

        body = b"".join(chunks)
        # Starlette exposes no public way to replay a stream it has consumed.
        request._body = body

        async def receive() -> dict:
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = receive
        return False


@dataclass
class FixedWindowLimiter:
    """Per-client request budget over a rolling window.

    In-process and per-worker, which is the honest scope: it protects one
    process from one caller. Several workers multiply the budget, and a
    distributed limiter belongs with the authentication this server does not
    have yet.
    """

    limit: int
    window_seconds: float
    _seen: dict[str, deque[float]] = field(default_factory=dict)

    def check(self, key: str, now: float | None = None) -> None:
        """Record a request, or raise if the caller is over budget."""
        if self.limit <= 0:
            return

        moment = time.monotonic() if now is None else now
        stamps = self._seen.setdefault(key, deque())

        cutoff = moment - self.window_seconds
        while stamps and stamps[0] <= cutoff:
            stamps.popleft()

        if len(stamps) >= self.limit:
            retry_after = max(1, int(stamps[0] + self.window_seconds - moment) + 1)
            raise LimitExceeded(
                429,
                f"too many requests; retry in {retry_after}s",
            )

        stamps.append(moment)

    def reset(self) -> None:
        self._seen.clear()


def client_key(request: Request) -> str:
    """Who to bill a request to.

    The socket address, not a forwarded header: a header is caller-supplied and
    would let anyone spend anyone else's budget. Behind a trusted proxy this is
    the proxy, which is a real limitation and the reason this is a floor rather
    than a defence.
    """
    return request.client.host if request.client else "unknown"


def enforce(limiter: FixedWindowLimiter, request: Request) -> None:
    """Apply a limiter, translating a refusal into the HTTP answer for it."""
    try:
        limiter.check(client_key(request))
    except LimitExceeded as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

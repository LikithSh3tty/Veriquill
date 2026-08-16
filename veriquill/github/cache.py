"""On-disk ETag cache.

GitHub does not charge a conditional request that returns 304 against the
hourly quota, so caching ETags is what makes repeat analysis of the same
candidate nearly free.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CachedResponse:
    etag: str
    payload: Any


class ResponseCache:
    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._dir / f"{digest}.json"

    def get(self, url: str) -> CachedResponse | None:
        path = self._path_for(url)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, KeyError):
            return None
        return CachedResponse(etag=raw["etag"], payload=raw["payload"])

    def set(self, url: str, etag: str, payload: Any) -> None:
        self._path_for(url).write_text(
            json.dumps({"etag": etag, "payload": payload}), encoding="utf-8"
        )

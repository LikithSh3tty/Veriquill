"""Serving the built interface from the API process.

In development Vite serves the interface and proxies /api to uvicorn. A
deployment has no Vite, and running the bundle on a second origin would mean a
CORS policy and a second host for no gain: the interface talks to exactly one
API. So the built files are served by the same process, behind the same origin,
and the browser's /api calls never leave it.

The mount is optional on purpose. A checkout that has never run `npm run build`
has no `ui/dist`, and the API has to start anyway — the CLI and the tests use it
without ever loading a page.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def mount_interface(app: FastAPI, dist: Path) -> bool:
    """Serve `dist` at the root, if it was built. Returns whether it was.

    Mounting at the root is safe only because every API route is registered
    first: Starlette matches routes in order, so the mount catches what is left
    rather than shadowing the API.
    """
    index = dist / "index.html"
    if not index.is_file():
        return False

    app.mount("/", StaticFiles(directory=dist, html=True), name="interface")
    return True

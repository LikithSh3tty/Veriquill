"""Who is calling, and whether the audit log can be believed.

The review gate records an actor for every dismissal, override, and approval,
and replaying those rows is supposed to reconstruct any state a comparison has
held. That guarantee was hollow: the actor was a string in the request body, so
anyone could sign an override with anyone's name, and the log recorded a claim
rather than a fact. An append-only log of unverified names is not an audit
trail.

So when keys are configured, the actor comes from the key and the one in the
body is refused rather than ignored. Refused, because a request that supplied a
different name meant something by it, and quietly overwriting it would leave the
caller believing they had recorded something they had not.

**Off unless configured.** With no keys set the API stays open, which is what a
local run and the test suite need. That is a real hole and the server says so at
startup rather than leaving it to be discovered.

Keys are compared with `secrets.compare_digest`, so a wrong key takes the same
time to reject as a right one and cannot be recovered a character at a time.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request

from veriquill.config import Settings, get_settings

logger = logging.getLogger(__name__)

#: Endpoints reachable without a key even when keys are configured. Liveness has
#: to answer an unauthenticated prober, and the interface has to load before it
#: can ask anyone for a key.
PUBLIC_PATHS = frozenset({"/health", "/api/health"})


@dataclass(frozen=True, slots=True)
class Identity:
    """Who the caller is, and whether that was actually established."""

    actor: str
    authenticated: bool

    @property
    def is_anonymous(self) -> bool:
        return not self.authenticated


ANONYMOUS = Identity(actor="", authenticated=False)


def _presented_key(request: Request) -> str | None:
    """The key on this request, from either header a client might reasonably use."""
    header = request.headers.get("authorization")
    if header:
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
        return None
    direct = request.headers.get("x-api-key")
    return direct.strip() if direct and direct.strip() else None


def resolve(request: Request, settings: Settings | None = None) -> Identity:
    """Identify the caller, or refuse the request.

    Returns anonymous when no keys are configured, because the server is then
    deliberately open. Raises 401 when keys are configured and the request does
    not carry a usable one.
    """
    settings = settings or get_settings()
    keys = settings.api_keys
    if not keys:
        return ANONYMOUS

    presented = _presented_key(request)
    if not presented:
        raise HTTPException(
            status_code=401,
            detail="this server requires an API key; send it as 'Authorization: Bearer <key>'",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Every configured key is compared, and comparison is constant time, so a
    # rejection reveals neither which key was close nor how long the right one is.
    matched = ""
    for key, actor in keys.items():
        if secrets.compare_digest(presented, key):
            matched = actor
    if not matched:
        raise HTTPException(status_code=401, detail="that API key is not recognised")

    return Identity(actor=matched, authenticated=True)


def actor_for(identity: Identity, requested: str | None) -> str:
    """The name to write into the audit log.

    Authenticated: the key's identity, and a request naming someone else is
    refused. Anonymous: whatever the caller typed, which is exactly as
    trustworthy as the open server it came from.
    """
    if identity.authenticated:
        supplied = (requested or "").strip()
        if supplied and supplied != identity.actor:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"this key acts as {identity.actor!r}; it cannot record an action "
                    f"as {supplied!r}. Leave the actor out and it will be filled in."
                ),
            )
        return identity.actor
    return (requested or "").strip()


def warn_if_open(settings: Settings | None = None) -> bool:
    """Say plainly, at startup, when nothing is guarding the audit log."""
    settings = settings or get_settings()
    if settings.api_keys:
        return False
    logger.warning(
        "No API keys are configured: every endpoint is open and every review "
        "action is signed with a name nobody verified. Set VERIQUILL_API_KEYS "
        "before letting anyone but you reach this server."
    )
    return True

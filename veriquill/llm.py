"""Building the optional Anthropic client, in one place.

Both optional passes - claim refinement and design review - need the same three
things to be true before a model is allowed to run, and neither should differ
from the other about what those are:

1. **The feature is switched on.** Both default to off. A pass that costs money
   and reaches a third party is not something a tool should start doing because
   an environment variable happened to be present.
2. **The SDK is installed.** `anthropic` is an optional dependency, so a plain
   `pip install veriquill` gives the fully deterministic tool and nothing here
   can run. That is the intended shape: the deterministic core is the product.
3. **Credentials resolve.** An unset key does not mean there are none - the SDK
   also resolves an `ant auth login` profile - so construction is attempted and
   only a failure counts as unavailable.

Any of the three failing yields `None`, which every caller treats as "skip this
pass". Nothing raises, because a missing optional feature must never be able to
fail an analysis.
"""

from __future__ import annotations

import logging
from typing import Any

from veriquill.config import Settings

logger = logging.getLogger(__name__)


def build_client(settings: Settings, *, enabled: bool, purpose: str) -> Any | None:
    """Return an Anthropic client, or None with the reason logged.

    `purpose` names the feature in the log line, so an operator who expected a
    pass to run can tell which of the three conditions was not met.
    """
    if not enabled:
        logger.debug("%s is disabled", purpose)
        return None

    try:
        import anthropic
    except ImportError:
        logger.info(
            "%s needs the anthropic package, which is an optional dependency; "
            "install it with: pip install 'veriquill[llm]'",
            purpose,
        )
        return None

    key = settings.anthropic_api_key.get_secret_value().strip()
    try:
        # An explicit key from settings wins, so `.env` genuinely controls this.
        # Without one the SDK falls back to its own resolution, which covers
        # ANTHROPIC_API_KEY and a logged-in profile.
        return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    except Exception:
        logger.info("no Anthropic credentials resolved; %s disabled", purpose)
        return None

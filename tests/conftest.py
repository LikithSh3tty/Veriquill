"""Shared fixtures.

The API's rate limiters are module-level and hold state between requests, which
is the point of them. In a test session that makes them shared between tests:
one module's requests spend the budget the next module's requests need, and a
test fails on the order it happened to run in rather than on anything it did.
Reset them around every test so each one starts from a full budget.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    from veriquill.api import main as api_main

    api_main._reads.reset()
    api_main._analyses.reset()
    yield
    api_main._reads.reset()
    api_main._analyses.reset()

"""The design reviewer may phrase judgment. It may not invent measurements."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from veriquill.codeeval.detect import profile_repo
from veriquill.codeeval.reviewer import (
    MAX_CONFIDENCE,
    DesignReviewer,
)
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.findings import Severity


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(
        github_token="t", data_dir=tmp_path / "data", code_review_enabled=True, **overrides
    )


def _repo(tmp_path) -> RepoContext:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text(
        "def handle(request):\n"
        "    if request.user:\n"
        "        return process(request)\n"
        "    return None\n",
        encoding="utf-8",
    )
    (root / "node_modules").mkdir()
    (root / "node_modules" / "dep.py").write_text("x = 1\n", encoding="utf-8")
    return RepoContext(
        full_name="cand/app",
        path=root,
        candidate_handle="cand",
        identities=frozenset({"cand"}),
        commits=[],
        metadata={},
    )


class FakeClient:
    """Stands in for the Anthropic client; records what it was asked."""

    def __init__(self, payload, stop_reason=None, raises=False):
        self.payload = payload
        self.stop_reason = stop_reason
        self.raises = raises
        self.prompts: list[str] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        if self.raises:
            raise RuntimeError("upstream is down")
        self.prompts.append(str(kwargs.get("messages")))
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=text)],
        )


def _review(tmp_path, payload, **kwargs):
    ctx = _repo(tmp_path)
    client = FakeClient(payload, **kwargs)
    reviewer = DesignReviewer(_settings(tmp_path), client=client)
    findings = reviewer.review(ctx, profile_repo(ctx.path))
    return findings, client


GOOD = {
    "observations": [
        {
            "path": "src/app.py",
            "line": 2,
            "quote": "    if request.user:",
            "concern": "Authentication is decided inline in the handler rather than in one place.",
            "severity": "medium",
        }
    ]
}


def test_a_grounded_observation_becomes_a_finding(tmp_path):
    findings, _ = _review(tmp_path, GOOD)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "codeeval.design_review"
    assert finding.evidence[0].path == "src/app.py"
    assert finding.evidence[0].line == 2


def test_the_finding_says_it_is_judgment_not_measurement(tmp_path):
    findings, _ = _review(tmp_path, GOOD)

    assert "judgment" in findings[0].rationale.lower()


def test_an_observation_whose_quote_does_not_match_the_file_is_dropped(tmp_path):
    payload = {
        "observations": [
            {**GOOD["observations"][0], "quote": "    if request.is_admin:"}
        ]
    }

    findings, _ = _review(tmp_path, payload)

    assert findings == []


def test_an_observation_pointing_at_a_missing_file_is_dropped(tmp_path):
    payload = {"observations": [{**GOOD["observations"][0], "path": "src/ghost.py"}]}

    findings, _ = _review(tmp_path, payload)

    assert findings == []


def test_an_observation_pointing_outside_the_repository_is_dropped(tmp_path):
    payload = {
        "observations": [
            {**GOOD["observations"][0], "path": "../../../etc/passwd", "line": 1}
        ]
    }

    findings, _ = _review(tmp_path, payload)

    assert findings == []


def test_an_observation_with_a_line_number_past_the_end_is_dropped(tmp_path):
    payload = {"observations": [{**GOOD["observations"][0], "line": 999}]}

    findings, _ = _review(tmp_path, payload)

    assert findings == []


def test_severity_is_capped_so_judgment_never_outranks_a_deterministic_flag(tmp_path):
    payload = {"observations": [{**GOOD["observations"][0], "severity": "critical"}]}

    findings, _ = _review(tmp_path, payload)

    assert findings[0].severity is Severity.MEDIUM


def test_confidence_is_capped_because_this_is_an_opinion(tmp_path):
    findings, _ = _review(tmp_path, GOOD)

    assert findings[0].confidence <= MAX_CONFIDENCE


def test_vendored_code_is_never_sent_for_review(tmp_path):
    _, client = _review(tmp_path, GOOD)

    assert "node_modules" not in client.prompts[0]


def test_a_refusal_produces_no_findings(tmp_path):
    findings, _ = _review(tmp_path, GOOD, stop_reason="refusal")

    assert findings == []


def test_unparseable_output_produces_no_findings(tmp_path):
    findings, _ = _review(tmp_path, "not json at all")

    assert findings == []


def test_an_upstream_failure_never_fails_the_run(tmp_path):
    findings, _ = _review(tmp_path, GOOD, raises=True)

    assert findings == []


def test_the_reviewer_is_unavailable_while_it_is_switched_off(tmp_path):
    ctx = _repo(tmp_path)
    settings = Settings(github_token="t", data_dir=tmp_path / "data")
    reviewer = DesignReviewer(settings)

    assert reviewer.available is False
    assert reviewer.review(ctx, profile_repo(ctx.path)) == []


def test_the_reviewer_stays_off_unless_it_is_switched_on(tmp_path):
    settings = Settings(github_token="t", data_dir=tmp_path / "data")

    assert settings.code_review_enabled is False


def test_the_number_of_observations_is_bounded(tmp_path):
    payload = {"observations": [GOOD["observations"][0] for _ in range(50)]}

    findings, _ = _review(tmp_path, payload)

    assert len(findings) <= 10


@pytest.mark.parametrize("missing", ["path", "quote", "concern"])
def test_an_incomplete_observation_is_dropped(tmp_path, missing):
    observation = {k: v for k, v in GOOD["observations"][0].items() if k != missing}

    findings, _ = _review(tmp_path, {"observations": [observation]})

    assert findings == []

import pytest

from veriquill.findings import EvidenceRef, Finding, Severity


def _ref() -> EvidenceRef:
    return EvidenceRef(repo="owner/repo", path="config.py", line=14)


def test_finding_holds_evidence():
    finding = Finding(
        check_id="security.hardcoded_secret",
        severity=Severity.MEDIUM,
        title="Hard-coded secret in code",
        rationale="An API key literal is committed in the repository.",
        confidence=0.9,
        evidence=(_ref(),),
    )
    assert finding.severity is Severity.MEDIUM
    assert finding.evidence[0].line == 14


def test_finding_without_evidence_is_rejected():
    with pytest.raises(ValueError, match="evidence"):
        Finding(
            check_id="x",
            severity=Severity.LOW,
            title="t",
            rationale="r",
            confidence=0.5,
            evidence=(),
        )


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_confidence_must_be_a_probability(bad):
    with pytest.raises(ValueError, match="confidence"):
        Finding(
            check_id="x",
            severity=Severity.LOW,
            title="t",
            rationale="r",
            confidence=bad,
            evidence=(_ref(),),
        )


def test_severity_orders_most_severe_first():
    unsorted = [Severity.LOW, Severity.CRITICAL, Severity.MEDIUM]
    assert sorted(unsorted, key=lambda s: s.rank) == [
        Severity.CRITICAL,
        Severity.MEDIUM,
        Severity.LOW,
    ]

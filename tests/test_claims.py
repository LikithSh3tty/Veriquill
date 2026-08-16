import pytest

from veriquill.claims.models import Claim, ClaimKind, ClaimSource


def _source() -> ClaimSource:
    return ClaimSource(document="resume.pdf", locator="line 12", excerpt="Led the auth redesign")


def test_claim_carries_its_provenance():
    claim = Claim(
        kind=ClaimKind.ROLE,
        text="Led the auth redesign",
        source=_source(),
        subject="auth",
    )
    assert claim.kind is ClaimKind.ROLE
    assert claim.source.locator == "line 12"


def test_claim_without_an_excerpt_is_rejected():
    """A claim must quote the text it came from.

    The specification requires claims with provenance ("candidate states X,
    source: resume line 12"). A claim that cannot point at its own source
    cannot be reconciled against evidence later.
    """
    with pytest.raises(ValueError, match="excerpt"):
        Claim(
            kind=ClaimKind.SKILL,
            text="Python",
            source=ClaimSource(document="resume.pdf", locator="line 3", excerpt="   "),
        )


def test_claim_without_a_locator_is_rejected():
    with pytest.raises(ValueError, match="locator"):
        Claim(
            kind=ClaimKind.SKILL,
            text="Python",
            source=ClaimSource(document="resume.pdf", locator="", excerpt="Python"),
        )


@pytest.mark.parametrize("bad", [-0.5, 1.5])
def test_claim_confidence_must_be_a_probability(bad):
    with pytest.raises(ValueError, match="confidence"):
        Claim(
            kind=ClaimKind.SKILL,
            text="Python",
            source=_source(),
            confidence=bad,
        )


def test_claims_are_hashable_so_they_can_be_deduplicated():
    a = Claim(kind=ClaimKind.SKILL, text="Python", source=_source())
    b = Claim(kind=ClaimKind.SKILL, text="Python", source=_source())
    assert len({a, b}) == 1

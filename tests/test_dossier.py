from veriquill.claims.models import Claim, ClaimKind, ClaimSource
from veriquill.dossier import build_dossier
from veriquill.findings import EvidenceRef, Finding, Severity
from veriquill.pipeline import RepoResult
from veriquill.reconcile.evidence import RepoEvidence
from veriquill.reconcile.models import Reconciliation, Verdict

REPO = RepoEvidence(
    full_name="cand/veriquill",
    languages={"Python": 10},
    authored_commits=40,
    total_commits=40,
    authored_loc=3000,
)


def _claim(text="veriquill", subject="veriquill") -> Claim:
    return Claim(
        kind=ClaimKind.PROJECT,
        text=text,
        source=ClaimSource(document="resume.txt", locator="line 7", excerpt=text),
        subject=subject,
    )


def _finding(check_id: str, severity: Severity) -> Finding:
    return Finding(
        check_id=check_id,
        severity=severity,
        title=check_id.replace(".", " "),
        rationale="because the evidence said so",
        confidence=0.8,
        evidence=(EvidenceRef(repo="cand/veriquill", path="config.py", line=14),),
    )


def _corroborated() -> Reconciliation:
    return Reconciliation(
        verdict=Verdict.CORROBORATED,
        rationale="authored 40 of 40 commits",
        confidence=0.9,
        claim=_claim(),
        evidence=(REPO,),
    )


def _contradicted() -> Reconciliation:
    return Reconciliation(
        verdict=Verdict.CONTRADICTED,
        rationale="authored 0 of 60 commits",
        confidence=0.7,
        claim=_claim("payments service", "payments"),
        evidence=(REPO,),
    )


def _unverifiable() -> Reconciliation:
    return Reconciliation(
        verdict=Verdict.UNVERIFIABLE,
        rationale="no public artifact",
        confidence=0.5,
        claim=_claim("internal trading platform", None),
    )


def test_dossier_has_every_section_the_specification_requires():
    dossier = build_dossier("cand", [], [])
    assert set(dossier) >= {
        "handle",
        "verdict_band",
        "verified_strengths",
        "red_flag_register",
        "claim_vs_evidence",
        "code_quality_snapshot",
        "gaps_and_open_questions",
        "provenance_and_fairness_notes",
    }


def test_the_verdict_band_is_never_a_bare_score():
    band = build_dossier("cand", [], [_corroborated()])["verdict_band"]
    assert isinstance(band["summary"], str) and band["summary"]
    assert "confidence" in band
    assert band["is_decision"] is False


def test_red_flags_are_ranked_most_severe_first():
    results = [
        RepoResult(
            full_name="cand/veriquill",
            findings=[
                _finding("codeeval.lint_debt", Severity.LOW),
                _finding("provenance.bulk_dump", Severity.HIGH),
                _finding("codeeval.no_tests", Severity.MEDIUM),
            ],
        )
    ]
    register = build_dossier("cand", results, [])["red_flag_register"]

    assert [f["severity"] for f in register] == ["high", "medium", "low"]


def test_a_contradiction_becomes_a_critical_red_flag():
    register = build_dossier("cand", [], [_contradicted()])["red_flag_register"]

    assert register
    assert register[0]["severity"] == "critical"
    assert "payments" in register[0]["title"].lower() or "payments" in str(register[0])


def test_every_red_flag_carries_evidence():
    results = [
        RepoResult(
            full_name="cand/veriquill",
            findings=[_finding("provenance.bulk_dump", Severity.HIGH)],
        )
    ]
    dossier = build_dossier("cand", results, [_contradicted()])

    assert all(flag["evidence"] for flag in dossier["red_flag_register"])


def test_corroborated_claims_become_verified_strengths():
    strengths = build_dossier("cand", [], [_corroborated()])["verified_strengths"]

    assert strengths
    assert strengths[0]["source"]["locator"] == "line 7"


def test_the_claim_table_reports_all_four_verdicts():
    table = build_dossier(
        "cand", [], [_corroborated(), _contradicted(), _unverifiable()]
    )["claim_vs_evidence"]

    assert table["counts"]["corroborated"] == 1
    assert table["counts"]["contradicted"] == 1
    assert table["counts"]["unverifiable"] == 1
    assert table["counts"]["undisclosed"] == 0


def test_unverifiable_claims_generate_interview_questions():
    questions = build_dossier("cand", [], [_unverifiable()])["gaps_and_open_questions"]

    assert questions
    assert any("trading platform" in q.lower() for q in questions)


def test_a_repository_that_failed_to_analyse_is_disclosed_not_hidden():
    results = [RepoResult(full_name="cand/broken", error="clone timed out")]
    dossier = build_dossier("cand", results, [])

    notes = " ".join(dossier["provenance_and_fairness_notes"])
    assert "cand/broken" in notes
    assert dossier["red_flag_register"] == []


def test_the_notes_state_that_this_is_advisory():
    notes = " ".join(build_dossier("cand", [], [])["provenance_and_fairness_notes"])
    assert "not a decision" in notes.lower() or "advisory" in notes.lower()


def test_a_clean_candidate_gets_no_manufactured_flags():
    dossier = build_dossier("cand", [], [_corroborated()])
    assert dossier["red_flag_register"] == []
    assert dossier["verdict_band"]["band"] == "evidence supports the claims made"

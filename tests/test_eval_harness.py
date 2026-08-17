import pytest

from veriquill.config import Settings
from veriquill.eval.groundtruth import CASES
from veriquill.eval.harness import evaluate, run_case


def _settings(tmp_path) -> Settings:
    return Settings(github_token="t", data_dir=tmp_path / "data")


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_each_labelled_case_behaves_as_labelled(case, tmp_path):
    """The ground truth is only useful if it actually holds.

    A failure here is a real finding: either the check regressed, or the label
    is wrong. Both need a human to look.
    """
    outcome = run_case(case, _settings(tmp_path), tmp_path)

    assert outcome.error is None, outcome.error
    assert not outcome.missed, f"{case.name} did not fire {sorted(outcome.missed)}"
    assert not outcome.false_alarms, (
        f"{case.name} raised forbidden {sorted(outcome.false_alarms)}"
    )


def test_the_healthy_control_case_produces_no_authenticity_flags(tmp_path):
    healthy = next(c for c in CASES if c.name == "healthy")
    outcome = run_case(healthy, _settings(tmp_path), tmp_path)

    provenance = {c for c in outcome.fired if c.startswith("provenance.")}
    assert provenance == set()


def test_the_report_has_the_sections_the_specification_asks_for(tmp_path):
    report = evaluate(_settings(tmp_path))

    assert set(report) >= {
        "overall",
        "per_check",
        "calibration",
        "cases",
        "limitations",
        "false_alarms_on_clean_cases",
    }
    assert report["cases_run"] == len(CASES)


def test_the_report_states_what_it_does_not_measure(tmp_path):
    limitations = " ".join(evaluate(_settings(tmp_path))["limitations"]).lower()
    assert "synthetic" in limitations
    assert "ranking" in limitations


def test_a_broken_case_is_reported_as_an_error_not_a_pass(tmp_path):
    from veriquill.eval.groundtruth import LabeledCase

    def explode(base):
        raise RuntimeError("fixture is broken")

    broken = LabeledCase(
        name="broken", description="deliberately broken", build=explode
    )
    outcome = run_case(broken, _settings(tmp_path), tmp_path)

    assert outcome.error is not None
    assert outcome.passed is False


def test_precision_and_recall_are_reported_separately(tmp_path):
    overall = evaluate(_settings(tmp_path))["overall"]
    assert "precision" in overall and "recall" in overall


def test_an_unlabelled_check_is_excluded_not_counted_against(tmp_path):
    """You cannot score against a label you never wrote.

    A case built to exercise commit cadence says nothing about test coverage.
    If such a case fires a test-coverage check, that is not a false positive
    -- it is a check the case simply does not measure.
    """
    from veriquill.eval.harness import CaseOutcome

    outcome = CaseOutcome(
        name="c",
        description="d",
        fired={"provenance.cadence_burst", "codeeval.unreferenced_modules"},
        expected={"provenance.cadence_burst"},
        forbidden={"provenance.bulk_dump"},
    )

    assert outcome.labelled == {"provenance.cadence_burst", "provenance.bulk_dump"}
    assert outcome.false_alarms == set()
    assert outcome.passed is True


def test_every_reference_cohort_names_real_cases():
    from veriquill.eval.groundtruth import REFERENCE_COHORTS

    known = {case.name for case in CASES}
    for cohort in REFERENCE_COHORTS:
        assert set(cohort.members) <= known, f"{cohort.name} names a case that does not exist"
        for order in cohort.orders:
            assert set(order) == set(cohort.members), (
                f"{cohort.name} has an ordering that does not cover its members"
            )


def test_the_ranking_report_correlates_the_tool_order_against_the_references():
    from tests.test_dimensions import flag, make_dossier
    from veriquill.eval.groundtruth import ReferenceCohort
    from veriquill.eval.harness import ranking_report

    def dossier(handle, flags):
        payload = make_dossier(red_flag_register=flags)
        payload["handle"] = handle
        return payload

    dossiers = {
        "clean": dossier("clean", []),
        "middling": dossier("middling", [flag("codeeval.no_tests", "medium")]),
        "poor": dossier("poor", [flag("provenance.bulk_dump", "critical")]),
    }
    cohort = ReferenceCohort(
        name="tiny",
        description="three cases, one ordering",
        members=("clean", "middling", "poor"),
        orders=(("clean", "middling", "poor"),),
    )

    report = ranking_report(dossiers, (cohort,))[0]

    assert report["tool_order"] == ["clean", "middling", "poor"]
    assert report["mean_spearman"] == pytest.approx(1.0)
    assert report["inter_rater_ceiling"]["mean_spearman"] is None


def test_the_ranking_report_reaches_the_full_report(tmp_path):
    report = evaluate(_settings(tmp_path))

    assert "ranking" in report
    entry = report["ranking"][0]
    assert entry["tool_order"]
    assert entry["inter_rater_ceiling"]["raters"] == 2
    assert "ceiling" in " ".join(report["limitations"]).lower()


def test_a_forbidden_check_that_fires_is_still_a_false_alarm(tmp_path):
    from veriquill.eval.harness import CaseOutcome

    outcome = CaseOutcome(
        name="c",
        description="d",
        fired={"provenance.bulk_dump"},
        expected=set(),
        forbidden={"provenance.bulk_dump"},
    )

    assert outcome.false_alarms == {"provenance.bulk_dump"}
    assert outcome.passed is False

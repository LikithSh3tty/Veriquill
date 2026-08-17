"""Running the labelled cases and reporting what the checks actually do.

The report separates three questions the specification asks separately:
how often a check is right when it fires (precision), how much it catches
(recall), and whether its stated confidence is earned (calibration).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from veriquill.codeeval.engine import run_codeeval
from veriquill.config import Settings
from veriquill.context import RepoContext
from veriquill.dossier import build_dossier
from veriquill.eval.groundtruth import CASES, REFERENCE_COHORTS, LabeledCase, ReferenceCohort
from veriquill.eval.metrics import calibration_bins, score_checks
from veriquill.eval.ranking import agreement, inter_rater_ceiling, ranks_from_order
from veriquill.findings import Finding
from veriquill.github.history import read_history
from veriquill.rank.compare import compare
from veriquill.reconcile.evidence import RepoEvidence
from veriquill.rubric import Rubric


@dataclass
class CaseOutcome:
    name: str
    description: str
    fired: set[str] = field(default_factory=set)
    expected: set[str] = field(default_factory=set)
    forbidden: set[str] = field(default_factory=set)
    findings: list[Finding] = field(default_factory=list)
    evidence: RepoEvidence | None = None
    error: str | None = None

    @property
    def labelled(self) -> set[str]:
        """Checks this case makes a claim about.

        A check nobody labelled for this case tells us nothing about it: the
        case was not built to exercise it either way. Scoring against absent
        labels would count correct behaviour as a false positive.
        """
        return self.expected | self.forbidden

    @property
    def missed(self) -> set[str]:
        return self.expected - self.fired

    @property
    def false_alarms(self) -> set[str]:
        """Forbidden checks that fired: the failures that matter most."""
        return self.fired & self.forbidden

    @property
    def passed(self) -> bool:
        return not self.missed and not self.false_alarms and self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.name,
            "description": self.description,
            "passed": self.passed,
            "fired": sorted(self.fired),
            "missed": sorted(self.missed),
            "false_alarms": sorted(self.false_alarms),
            "error": self.error,
        }


def run_case(case: LabeledCase, settings: Settings, workdir: Path) -> CaseOutcome:
    from veriquill.pipeline import build_evidence
    from veriquill.provenance.engine import run_provenance

    outcome = CaseOutcome(
        name=case.name,
        description=case.description,
        expected=set(case.expected),
        forbidden=set(case.forbidden),
    )

    try:
        repo_path = case.build(workdir)
        ctx = RepoContext(
            full_name=f"eval/{case.name}",
            path=repo_path,
            candidate_handle="eval",
            identities=frozenset(i.lower() for i in case.identities),
            commits=read_history(repo_path),
            metadata=dict(case.metadata),
        )
        findings = run_provenance(ctx, settings, known_fingerprints={})
        findings.extend(run_codeeval(ctx, settings))
        outcome.findings = findings
        outcome.fired = {f.check_id for f in findings}
        # Ranking reads dossiers, and a dossier needs the same evidence view the
        # pipeline builds, so the eval path builds it the same way.
        outcome.evidence = build_evidence(ctx, findings)
    except Exception as exc:  # a broken case must not silently pass
        outcome.error = f"{type(exc).__name__}: {exc}"

    return outcome


def case_dossier(outcome: CaseOutcome) -> dict[str, Any]:
    """The dossier a case would produce, so ranking can be measured on it."""
    from veriquill.pipeline import RepoResult

    repo = RepoResult(
        full_name=f"eval/{outcome.name}",
        findings=list(outcome.findings),
        error=outcome.error,
        evidence=outcome.evidence,
    )
    dossier = build_dossier(outcome.name, [repo], [])
    return dossier


def ranking_report(
    dossiers: dict[str, dict[str, Any]],
    cohorts: tuple[ReferenceCohort, ...] = REFERENCE_COHORTS,
) -> list[dict[str, Any]]:
    """Correlate Veriquill's ordering with each reference ordering.

    The correlation is reported next to the inter-rater ceiling, because a
    figure without that denominator invites a comparison against a perfection
    the humans never reached either.
    """
    rubric = Rubric.from_dict({"name": "eval-default", "weights": {}})
    reports: list[dict[str, Any]] = []

    for cohort in cohorts:
        payloads = [dossiers[name] for name in cohort.members if name in dossiers]
        result = compare(payloads, rubric)
        tool_ranks = {row["handle"]: float(row["rank"]) for row in result["ranked"]}

        against = [
            agreement(tool_ranks, ranks_from_order(list(order))) for order in cohort.orders
        ]
        coefficients = [a["spearman"] for a in against if a["spearman"] is not None]

        reports.append(
            {
                "cohort": cohort.name,
                "description": cohort.description,
                "tool_order": [row["handle"] for row in result["ranked"]],
                "unranked": [row["handle"] for row in result["unranked"]],
                "against_reference_orders": against,
                "mean_spearman": (
                    round(sum(coefficients) / len(coefficients), 4) if coefficients else None
                ),
                "inter_rater_ceiling": inter_rater_ceiling([list(o) for o in cohort.orders]),
            }
        )

    return reports


def evaluate(
    settings: Settings, cases: tuple[LabeledCase, ...] = CASES
) -> dict[str, Any]:
    outcomes: list[CaseOutcome] = []

    dossiers: dict[str, dict[str, Any]] = {}

    with tempfile.TemporaryDirectory(prefix="veriquill-eval-") as raw:
        workdir = Path(raw)
        for case in cases:
            outcome = run_case(case, settings, workdir)
            outcomes.append(outcome)
            # Built inside the temporary directory: the evidence view reads the
            # working tree, which is gone once this block exits.
            dossiers[outcome.name] = case_dossier(outcome)

    # Score only over checks each case actually labels, in both directions.
    scores = score_checks(
        [(o.fired & o.labelled, o.expected) for o in outcomes]
    )

    # Calibration is judged on the same labelled subset, for the same reason:
    # a finding whose check the case never labelled is not evidence either way.
    observations: list[tuple[float, bool]] = [
        (finding.confidence, finding.check_id in outcome.expected)
        for outcome in outcomes
        for finding in outcome.findings
        if finding.check_id in outcome.labelled
    ]
    bins = calibration_bins(observations)

    true_positives = sum(s.true_positives for s in scores.values())
    false_positives = sum(s.false_positives for s in scores.values())
    false_negatives = sum(s.false_negatives for s in scores.values())
    fired_total = true_positives + false_positives
    expected_total = true_positives + false_negatives

    false_alarms = sorted(
        {check for o in outcomes for check in o.false_alarms}
    )

    return {
        "cases_run": len(outcomes),
        "cases_passed": sum(1 for o in outcomes if o.passed),
        "overall": {
            "precision": round(true_positives / fired_total, 4) if fired_total else 0.0,
            "recall": round(true_positives / expected_total, 4)
            if expected_total
            else 0.0,
            "true_positives": true_positives,
            "false_positives": false_positives,
            "false_negatives": false_negatives,
        },
        "false_alarms_on_clean_cases": false_alarms,
        "per_check": [score.to_dict() for score in scores.values()],
        "calibration": [b.to_dict() for b in bins if b.count],
        "ranking": ranking_report(dossiers),
        "cases": [o.to_dict() for o in outcomes],
        "limitations": [
            "These cases are synthetic repositories built to known shapes. They "
            "measure whether each check fires on the shape it targets, not "
            "whether its thresholds suit real portfolios.",
            "No hand-labelled real profiles are included yet, so no claim is "
            "made about precision in the field.",
            "Scoring covers only the checks each case explicitly labels as "
            "expected or forbidden. Checks a case says nothing about are "
            "excluded rather than counted as errors.",
            "Ranking correlation is measured against orderings this project "
            "wrote for its own synthetic cases, not against an independent "
            "expert panel. Read the coefficient against the inter-rater "
            "ceiling reported beside it, and treat both as provisional until "
            "real raters order real candidates.",
        ],
    }

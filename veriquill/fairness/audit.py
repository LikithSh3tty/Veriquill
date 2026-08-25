"""The bias audit (specification §11).

Veriquill treats itself as an automated employment decision tool, so it ships an
audit artifact rather than an assurance. Two things make that awkward, and both
are handled here rather than wished away.

First, Veriquill never infers a protected attribute, so it cannot compute a
selection rate by group on its own. Group labels have to come from the recruiter,
who already holds that data for their own reporting. When they are supplied, the
audit reports selection rate per group and the impact ratio against the
four-fifths rule.

Second, most runs will have no labels at all, and an audit that reports nothing
in that case is useless exactly when it is most needed. So the unlabelled path
still reports what it can measure without any protected data: how evenly the
tool was able to gather evidence across the cohort. Systematically thinner
coverage for some candidates is where disparate impact enters this design, since
a portfolio in a language Veriquill does not analyse in depth, or one held in
private repositories, produces less evidence through no fault of the candidate.
"""

from __future__ import annotations

from typing import Any

FOUR_FIFTHS = 0.8

DISCLAIMER = (
    "This is a self-audit artifact, not an independent bias audit and not a "
    "legal certification. It reports what this tool can measure about its own "
    "output. Jurisdictions such as New York City require an independent "
    "auditor, and no number here substitutes for one."
)

COVERAGE_SPREAD_WARNING = 0.25
MIN_GROUP_SIZE = 2


def impact_ratio(rate_a: float, rate_b: float) -> float | None:
    """The smaller selection rate over the larger; None when nobody was selected."""
    higher = max(rate_a, rate_b)
    if higher == 0:
        return None
    return min(rate_a, rate_b) / higher


def _rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    return list(result.get("ranked") or [])


def _coverage_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """How evenly evidence was gathered, which needs no protected data at all."""
    coverages = [
        {"handle": row["handle"], "coverage": float(row["score"]["coverage"])}
        for row in rows
    ]
    if not coverages:
        return {"lowest": None, "highest": None, "spread": 0.0, "per_candidate": []}

    ordered = sorted(coverages, key=lambda item: (item["coverage"], item["handle"]))
    return {
        "lowest": ordered[0],
        "highest": ordered[-1],
        "spread": round(ordered[-1]["coverage"] - ordered[0]["coverage"], 6),
        "per_candidate": ordered,
    }


def _selection(
    rows: list[dict[str, Any]], groups: dict[str, str], top_k: int
) -> list[dict[str, Any]]:
    selected = {row["handle"] for row in rows[:top_k]}

    tallies: dict[str, list[int]] = {}
    for row in rows:
        group = groups.get(row["handle"])
        if group is None:
            continue
        counts = tallies.setdefault(group, [0, 0])
        counts[1] += 1
        if row["handle"] in selected:
            counts[0] += 1

    return [
        {
            "group": group,
            "selected": counts[0],
            "considered": counts[1],
            "selection_rate": round(counts[0] / counts[1], 6) if counts[1] else 0.0,
        }
        for group, counts in sorted(tallies.items())
    ]


def _flag_rates(
    rows: list[dict[str, Any]], groups: dict[str, str], dossiers: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """How often each check fires per group.

    A check that fires far more often for one group is worth a human look even
    when the final ordering passes: the ordering can look even while the reasons
    behind it do not.
    """
    checks: set[str] = set()
    per_group: dict[str, list[str]] = {}

    for row in rows:
        group = groups.get(row["handle"])
        if group is None:
            continue
        per_group.setdefault(group, []).append(row["handle"])
        for flag in (dossiers.get(row["handle"]) or {}).get("red_flag_register") or []:
            checks.add(str(flag.get("check_id")))

    rates: list[dict[str, Any]] = []
    for check in sorted(checks):
        for group, handles in sorted(per_group.items()):
            fired = sum(
                1
                for handle in handles
                if any(
                    str(flag.get("check_id")) == check
                    for flag in (dossiers.get(handle) or {}).get("red_flag_register") or []
                )
            )
            rates.append(
                {
                    "check_id": check,
                    "group": group,
                    "fired_for": fired,
                    "candidates": len(handles),
                    "rate": round(fired / len(handles), 6) if handles else 0.0,
                }
            )

    return rates


def audit_comparison(
    result: dict[str, Any],
    groups: dict[str, str] | None = None,
    top_k: int = 1,
    dossiers: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Audit one ranked comparison for disparate impact and uneven evidence.

    `groups` maps candidate handle to a group label the recruiter supplies from
    their own records. Veriquill never derives it. A candidate with no label is
    reported as unlabelled and excluded from the rate arithmetic rather than
    bucketed into a guess.
    """
    rows = _rows(result)
    labels = dict(groups or {})
    payloads = dict(dossiers or {})
    notes: list[str] = []

    coverage = _coverage_report(rows)
    if coverage["spread"] > COVERAGE_SPREAD_WARNING:
        notes.append(
            f"Evidence coverage varies by {coverage['spread']:.2f} across this cohort. "
            "Uneven coverage is the most likely route to disparate impact here, "
            "because a candidate Veriquill could read less of scores with a wider "
            "band through no fault of their own."
        )

    unlabelled = sorted(row["handle"] for row in rows if row["handle"] not in labels)
    selection = _selection(rows, labels, top_k) if labels else []
    flag_rates = _flag_rates(rows, labels, payloads) if labels and payloads else []

    ratio: float | None = None
    passes: bool | None = None

    if len(selection) >= 2:
        rates = [row["selection_rate"] for row in selection]
        ratio = impact_ratio(min(rates), max(rates))

        # A group of one produces a selection rate of exactly 0% or 100%, and
        # an impact ratio built from those says nothing about anybody. The
        # rate is still reported, because describing the cohort is useful,
        # but the verdict is withheld: the same distinction this tool draws
        # everywhere between not knowing and being satisfied.
        undersized = [
            row["group"] for row in selection if row["considered"] < MIN_GROUP_SIZE
        ]
        if undersized:
            notes.append(
                f"Group(s) {', '.join(repr(g) for g in undersized)} hold fewer than "
                f"{MIN_GROUP_SIZE} candidates: too small for a four-fifths verdict, so "
                "none is reported. "
                "A rate over one candidate is 0% or 100% whatever the tool did, and "
                "a pass built on that would be false comfort while a failure would "
                "be a false alarm. The rates below describe the cohort; they do not "
                "measure it."
            )
        else:
            passes = ratio is not None and ratio >= FOUR_FIFTHS
    elif labels:
        notes.append(
            "Only one group was labelled, so no comparison between groups is possible."
        )
    else:
        notes.append(
            "No group labels were supplied, so no selection-rate comparison was run. "
            "Veriquill never infers a protected attribute; supply labels from your own "
            "records to audit selection rates."
        )

    if unlabelled and labels:
        notes.append(
            f"{len(unlabelled)} candidate(s) had no group label and were left out of "
            "the rate arithmetic rather than guessed at."
        )

    return {
        "cohort_size": len(rows),
        "top_k": top_k,
        "groups_supplied": bool(labels),
        "unlabelled_candidates": unlabelled,
        "selection": selection,
        "impact_ratio": round(ratio, 6) if ratio is not None else None,
        "passes_four_fifths": passes,
        "four_fifths_threshold": FOUR_FIFTHS,
        "flag_rates": flag_rates,
        "coverage": coverage,
        "notes": notes,
        "disclaimer": DISCLAIMER,
    }

"""How closely Veriquill's ordering tracks a human ordering (specification §10).

A correlation figure on its own invites a comparison nobody can win. Humans
ranking the same candidates do not agree with each other either, so the honest
denominator is the inter-rater ceiling: the mean agreement between the human
orderings themselves. A tool scoring 0.7 against a panel that agrees with itself
at 0.72 is close to the limit of what the task allows, and saying "0.7" alone
would hide that.

Both coefficients are tie-aware, because Veriquill deliberately reports tie
groups rather than inventing an order it cannot justify.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations
from math import sqrt
from typing import Any


def average_ranks(values: Sequence[float]) -> list[float]:
    """Rank ascending, splitting ties across the positions they occupy."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)

    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        shared = (position + end) / 2 + 1
        for index in range(position, end + 1):
            ranks[order[index]] = shared
        position = end + 1

    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Pearson correlation of the rank vectors; None when it is undefined."""
    if len(x) != len(y):
        raise ValueError("spearman needs two sequences of the same length")
    if len(x) < 2:
        return None

    rx, ry = average_ranks(x), average_ranks(y)
    mean_x = sum(rx) / len(rx)
    mean_y = sum(ry) / len(ry)

    covariance = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry))
    variance_x = sum((a - mean_x) ** 2 for a in rx)
    variance_y = sum((b - mean_y) ** 2 for b in ry)

    if variance_x == 0 or variance_y == 0:
        # One side ranked everyone equally; there is no ordering to correlate.
        return None

    return covariance / sqrt(variance_x * variance_y)


def kendall_tau_b(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Tau-b: concordant minus discordant pairs, corrected for ties."""
    if len(x) != len(y):
        raise ValueError("kendall_tau_b needs two sequences of the same length")
    if len(x) < 2:
        return None

    concordant = discordant = ties_x = ties_y = 0
    for i, j in combinations(range(len(x)), 2):
        dx = x[i] - x[j]
        dy = y[i] - y[j]
        product = dx * dy
        if product > 0:
            concordant += 1
        elif product < 0:
            discordant += 1
        else:
            if dx == 0:
                ties_x += 1
            if dy == 0:
                ties_y += 1

    denominator = sqrt((concordant + discordant + ties_x) * (concordant + discordant + ties_y))
    if denominator == 0:
        return None

    return (concordant - discordant) / denominator


def ranks_from_order(order: Sequence[str]) -> dict[str, float]:
    """Turn a best-first ordering into ranks, 1 for the top."""
    return {handle: float(position) for position, handle in enumerate(order, start=1)}


def agreement(
    tool_ranks: dict[str, float], reference_ranks: dict[str, float]
) -> dict[str, Any]:
    """Compare two rankings over the candidates they both cover."""
    shared = sorted(set(tool_ranks) & set(reference_ranks))
    ignored = sorted((set(tool_ranks) | set(reference_ranks)) - set(shared))

    tool = [tool_ranks[handle] for handle in shared]
    reference = [reference_ranks[handle] for handle in shared]

    return {
        "candidates_compared": len(shared),
        "ignored": ignored,
        "spearman": spearman(tool, reference),
        "kendall_tau_b": kendall_tau_b(tool, reference),
    }


def inter_rater_ceiling(orders: Sequence[Sequence[str]]) -> dict[str, Any]:
    """Mean pairwise agreement between the human orderings themselves.

    This is the honest ceiling for the tool: where humans disagree, no ordering
    can be called correct.
    """
    if len(orders) < 2:
        return {
            "raters": len(orders),
            "pairs": 0,
            "mean_spearman": None,
            "note": (
                "only one reference ordering is available, so no inter-rater "
                "ceiling can be reported"
            ),
        }

    coefficients: list[float] = []
    for left, right in combinations(orders, 2):
        result = agreement(ranks_from_order(left), ranks_from_order(right))
        if result["spearman"] is not None:
            coefficients.append(result["spearman"])

    mean = sum(coefficients) / len(coefficients) if coefficients else None
    return {
        "raters": len(orders),
        "pairs": len(list(combinations(range(len(orders)), 2))),
        "mean_spearman": mean,
        "note": (
            "mean pairwise agreement between the reference orderings; the tool "
            "cannot meaningfully exceed this"
        ),
    }

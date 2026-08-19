"""Choosing which repositories to read when an account holds too many.

Cloning twenty-five repositories to answer a question about five is slow, and on
a large account most of them are coursework, forks, or a personal site that has
nothing to do with the posting. So above a threshold Veriquill reads the most
relevant ones and says plainly which it skipped.

Three rules keep this from quietly deciding a candidate's fate:

1. **Selection runs on metadata GitHub already returned** — language, topics,
   description, size, recency, fork status. Nothing is cloned to decide whether
   to clone it, so the saving is real.
2. **Every choice carries its reason**, and every skipped repository is named. A
   candidate can ask why their best work was not read.
3. **Skipping is coverage, never a finding.** The dossier counts the whole
   account, so reading five of twenty-one lowers coverage and widens the
   confidence band. A partial look must never read as a full one.
"""

from __future__ import annotations

import re
from typing import Any

DEFAULT_LIMIT = 5
DEFAULT_THRESHOLD = 20

# Languages a posting might name, mapped to what GitHub reports.
LANGUAGE_TERMS = {
    "python": "Python",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "go": "Go",
    "golang": "Go",
    "rust": "Rust",
    "java": "Java",
    "kotlin": "Kotlin",
    "swift": "Swift",
    "ruby": "Ruby",
    "php": "PHP",
    "c++": "C++",
    "c#": "C#",
    "scala": "Scala",
}

# Weightings. A language match is the strongest pre-clone signal a posting gives.
LANGUAGE_MATCH = 6.0
TOPIC_MATCH = 3.0
DESCRIPTION_MATCH = 2.0
FORK_PENALTY = -4.0
SIZE_WEIGHT = 1.0
RECENCY_WEIGHT = 1.5

_WORD = re.compile(r"[a-z0-9+#.]+")
# Words too common in a posting to say anything about a repository.
_STOPWORDS = frozenset(
    """a an and are as at be by for from has have in into is it its of on or our
    that the their they this to we will with you your work working team teams
    experience strong good great role join build building code coding software
    engineer engineering developer development company product products
    """.split()
)


def _terms(text: str) -> set[str]:
    return {
        word
        for word in _WORD.findall((text or "").lower())
        if len(word) > 2 and word not in _STOPWORDS
    }


def _languages_named(text: str) -> set[str]:
    haystack = (text or "").lower()
    return {
        language
        for term, language in LANGUAGE_TERMS.items()
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", haystack)
    }


def _score(repo: dict[str, Any], terms: set[str], languages: set[str]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    language = repo.get("language")
    if language and language in languages:
        score += LANGUAGE_MATCH
        reasons.append(f"written in {language}, which the posting names")

    topics = {str(t).lower() for t in repo.get("topics") or []}
    shared_topics = sorted(topics & terms)
    if shared_topics:
        score += TOPIC_MATCH * min(len(shared_topics), 2)
        reasons.append(f"tagged {', '.join(shared_topics[:3])}")

    described = _terms(repo.get("description") or "") & terms
    if described:
        score += DESCRIPTION_MATCH * min(len(described), 2)
        reasons.append(f"description mentions {', '.join(sorted(described)[:3])}")

    if repo.get("fork"):
        score += FORK_PENALTY
        reasons.append("a fork, so it is read only if nothing better is available")

    # Size and recency break ties and carry the whole decision when no posting
    # was supplied. Both are capped so one enormous repository cannot crowd out
    # everything a posting actually asked for.
    size_kb = float(repo.get("size") or 0)
    size_points = min(size_kb / 5000.0, 1.0) * SIZE_WEIGHT
    score += size_points

    pushed = str(repo.get("pushed_at") or "")
    if pushed >= "2025":
        score += RECENCY_WEIGHT
        reasons.append("pushed recently")
    elif pushed >= "2024":
        score += RECENCY_WEIGHT / 2

    if not reasons:
        reasons.append("selected on size and recency; the posting named nothing it matches")

    return score, reasons


def select_repositories(
    repos: list[dict[str, Any]],
    job_description: str = "",
    limit: int = DEFAULT_LIMIT,
    threshold: int = DEFAULT_THRESHOLD,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pick the repositories worth reading, and name the ones left unread.

    Accounts at or below `threshold` are read in full: trimming a small portfolio
    saves little and risks missing the one repository that mattered.
    """
    if len(repos) <= threshold:
        return ([{"repository": r, "reasons": ["the whole account was read"]} for r in repos], [])

    terms = _terms(job_description)
    languages = _languages_named(job_description)

    ranked = sorted(
        ((_score(r, terms, languages), r) for r in repos),
        key=lambda pair: (-pair[0][0], str(pair[1].get("name", ""))),
    )

    selected = [
        {"repository": repo, "reasons": reasons, "score": round(score, 3)}
        for (score, reasons), repo in ranked[:limit]
    ]
    skipped = [
        {
            "repository": repo,
            "reason": (
                f"not among the {limit} most relevant of {len(repos)} repositories "
                "for this posting; it was not read, and that is recorded as missing "
                "coverage rather than as a finding"
            ),
        }
        for (_score_value, _reasons), repo in ranked[limit:]
    ]

    return selected, skipped

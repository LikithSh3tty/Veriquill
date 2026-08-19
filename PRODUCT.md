# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Existing codebase. Backend: Python 3.11, FastAPI, SQLAlchemy, SQLite. Frontend:
React 19 + TypeScript on Vite, in `ui/`, with Vitest and Testing Library. No CSS
framework; hand-written CSS with custom properties.

## Users

**Primary: a recruiter screening a cohort.** Not an engineer. Compares several
candidates in one sitting and needs to see who to look at first and why. Reads
plain language, not commit shas. Density must serve scanning, not exhaustive
detail.

**Secondary: the named reviewer who signs off.** Same person or their manager,
acting under the review gate: they dismiss or confirm individual flags with a
written reason, then approve a revision. Their decisions are permanent and
attributed.

## Product Purpose

Veriquill verifies whether a portfolio is genuinely the candidate's own iterative
work, evaluates the code in it, reconciles what the candidate claims against what
the evidence shows, and ranks a cohort against a recruiter-supplied rubric — for a
human to review. It supports a hiring decision and never makes one.

Success is a recruiter who can defend their shortlist: every position traceable to
evidence, every flag dismissible with a reason on the record.

## Positioning

Evidence-first, and structurally so rather than as a claim. A finding cannot be
constructed without at least one evidence reference; a score is never emitted
without its coverage and confidence band; a human override is recorded beside the
machine result and never replaces it. Competing screening tools rank on activity
signals and cannot show their working.

## Durable product facts future work must preserve

- **Advisory, never a decision.** No auto-reject, no auto-hire. Every surface says so.
- **A flag is a question, not proof of wrongdoing.** Innocent explanations exist for
  every check, and the copy must never imply otherwise.
- **Thin evidence widens the band; it never lowers the score.** A dimension nobody
  could measure reads "not measured" with a reason, never as a zero. A candidate
  nothing could be measured for is reported unranked, not last.
- **Ties are real.** Where confidence bands overlap, the tool cannot separate those
  candidates and must show that rather than imply an order.
- **The gate blocks export.** Nothing leaves until a named human approves the current
  revision; any later change reopens it.
- **Overrides annotate, never erase.** The machine result stays visible next to the
  human one, with the reason and the actor.
- **No protected attributes.** Date of birth, gender, marital status, nationality,
  religion, health, and photos are redacted at ingestion and must never appear in
  any view.

## Terminology

Cohort, comparison, candidate, dossier, red flag, flag id, dimension, coverage,
confidence band, tie group, revision, review gate, audit log, rubric, impact ratio.

## Accessibility

Keyboard operable with visible focus; reduced motion respected; colour never the
sole carrier of meaning (severity and human-vs-machine distinctions carry text
labels too).

## Open decisions

- Authentication is not built. `actor` is currently whatever the caller types.
- The landing page is new work; no prior marketing copy, imagery, or brand assets
  exist to preserve.

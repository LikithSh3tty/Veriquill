# Veriquill

Proof over polish. Evidence-first hiring intelligence that verifies a portfolio
before it ranks anyone.

Veriquill answers two questions generic screening tools skip: is this work
genuinely the candidate's own iterative effort, and is the code any good.
Every finding it emits cites the commit, file, or line that produced it.

## Status

Implemented: repository ingestion, deterministic provenance and authenticity
checks, static code evaluation (M1); résumé and LinkedIn claim workers (M2);
reconciliation and the candidate dossier (M3); rubric-weighted ranking with a
blocking human review gate and an append-only override log (M4); the
evaluation harness measuring the checks against hand-labelled cases and the
ranking against reference orderings (M5); and the fairness controls, bias audit,
and disclosure pack (M6).

Findings are advisory. Veriquill never auto-rejects, never auto-hires, and never
treats a flag as proof of wrongdoing. No LLM sits on the provenance, code
evaluation, or ranking path: those are deterministic and reproducible. The only
optional LLM call refines the phrasing of claims already extracted from a
candidate's own documents.

## What Veriquill checks

**Provenance and authenticity (deterministic).** Commit cadence, bulk dumps
with no development history, forks presented as original work, template and
dependency inflation, cross-profile duplication, and whether the candidate
actually authored the commits.

**Code evaluation (static analysis).** Cyclomatic complexity, security hygiene,
lint compliance, test quality measured by assertion meaningfulness rather than
test count, and modules nothing imports. Python is analysed in depth; other
languages are detected and counted, and the output says so explicitly.

**Design review (optional, off by default).** Set `VERIQUILL_CODE_REVIEW_ENABLED=true`
to let a model phrase the judgment static analysis cannot reach — responsibilities
that are tangled, decisions duplicated across modules, error handling that hides
failures. It runs under hard constraints: every observation must quote a line that
appears verbatim at the file and line it cites, or it is discarded; its severity is
capped at medium and its confidence at 0.5, so a judgment can never outrank
something that was measured; it is told not to report metrics, because every number
in the dossier comes from static analysis; and it only ever sees authored code,
never vendored trees. With the setting off, or with no credentials resolved, the
pipeline is fully deterministic.

Every finding carries at least one evidence reference. That is a structural
guarantee, not a convention: a finding with empty evidence cannot be
constructed.

## Requirements

- Python 3.11 or newer
- Git available on PATH
- A GitHub personal access token

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate      # Windows
pip install -e ".[dev]"
cp .env.example .env        # then edit .env and add your token
```

## Usage

```bash
veriquill analyse octocat --output dossier.json
```

Or run the API:

```bash
uvicorn veriquill.api.main:app --reload
```

`POST /analyse` with `{"handle": "octocat"}` starts a run, `GET /runs/{run_id}`
returns it. Rubrics, comparisons, review actions, and exports have endpoints
mirroring the CLI commands below.

## Comparing candidates

Ranking reads stored dossiers. It never re-analyses anyone, makes no network
call, and involves no LLM.

```bash
veriquill rubric-add rubric.json
veriquill rank --rubric backend-hire --candidate alice --candidate bob
veriquill review-show 1
veriquill review-flag 1 --candidate bob --flag 3f2a91c40b7e \
  --action dismiss --actor "you@example.com" --reason "employer-owned import"
veriquill review-approve 1 --actor "you@example.com"
veriquill export-comparison 1 --output comparison.json
veriquill audit 1
```

A rubric sets weights over six fixed dimensions — authenticity, code quality,
claim corroboration, test quality, security, breadth. Unlisted dimensions take
their default weight, and an unknown dimension name is refused rather than
ignored.

**A comparison cannot be exported until a named human approves it.** An approval
covers exactly the revision it saw: any later review action bumps the revision
and reopens the gate.

**Thin evidence widens the confidence band; it never lowers the score.** A
dimension nobody could measure is dropped from the weighting and listed with the
reason it could not be measured, so a candidate with private repositories or a
non-Python portfolio reads as "we could not tell", not "weak". A candidate
nothing could be measured for is reported unranked rather than placed last.

**Overrides never edit the machine result.** Dismissals and band overrides are
recorded with the actor and the reason, and the export carries both what
Veriquill said and what the human changed. The audit log is append-only:
replaying it reconstructs any state the comparison has held.

There is no authentication. `--actor` is whatever the caller types; a real
deployment must supply an authenticated identity.

## Review dashboard

A React dashboard for the human review gate lives in `ui/`. It reads the API and
records decisions; it holds no scoring logic of its own.

```bash
uvicorn veriquill.api.main:app --reload   # terminal one
cd ui && npm install && npm run dev       # terminal two
```

Open `http://localhost:5173/?comparison=1`. The dev server proxies `/api` to the
API on port 8000.

Every candidate's confidence band is drawn on one shared axis, so where two bands
overlap you can see that the evidence does not separate those candidates — tied
candidates are bracketed together rather than listed in an order that would imply
a difference. Colour marks who said what: the machine's numbers are in ink, and
every human dismissal or override is written beside them in blue, the same way
the audit log records them without touching the machine result.

```bash
cd ui
npm test        # component and API-client tests
npm run build   # production bundle
npm run lint    # typecheck
```

## Fairness and compliance

Veriquill treats itself as an automated employment decision tool and ships the
artifacts that position demands.

**Protected attributes are removed at the door.** Resumes in many countries state
date of birth, marital status, nationality, religion, caste, blood group, or
attach a photograph. Those fields are detected by label and redacted before
parsing, before any model call, and before anything is stored, so they never
reach a claim, a score, a log, or the recruiter's screen. The dossier records
that a field was present and removed, and never what it contained.

**The bias audit runs with or without group labels.**

```bash
veriquill fairness-report 1 --output fairness.json
veriquill fairness-report 1 --groups groups.json --top-k 3 --format markdown -o pack.md
```

Veriquill never infers a protected attribute, so selection-rate arithmetic needs
group labels supplied from your own records (`{"alice": "A", "bob": "B"}`). Given
them, it reports selection rate per group, the impact ratio against the
four-fifths rule, and per-check flag rates, because an ordering can look even
while the reasons behind it do not.

Without labels it still audits what needs no protected data at all: how evenly
evidence could be gathered across the cohort. That is the most likely route to
disparate impact in this design, since a portfolio in a language Veriquill does
not analyse in depth, or one held in private repositories, yields less evidence
through no fault of the candidate.

**The disclosure pack is generated from the running code**, not maintained by
hand: measured dimensions come from the rubric and excluded attributes from the
scanner itself, so neither can drift out of date. It states what is measured and
on what evidence, what is excluded, how the human gate and audit log work, and
what the tool must never do.

This is a self-audit artifact. Jurisdictions such as New York City require an
independent bias audit, and nothing here replaces one.

## Rate limits

Veriquill requires a GitHub token and refuses to run without one:
unauthenticated REST allows 60 requests per hour, authenticated allows 5,000.

Commit history and file contents come from `git clone`, which runs over git
transport and is not billed against that quota. REST is used only to resolve
the candidate and list their repositories: an eight-repository account costs
exactly **two** REST calls. Those calls are ETag-cached and a 304 response is
free, so repeat runs on the same candidate cost almost nothing.

Clones are deliberately complete rather than `--filter=blob:none`. Partial
clones look cheaper and are much worse here: provenance reads history with
`git log --numstat`, which diffs every commit and therefore needs blob
contents, so git back-fills them from the remote one round trip at a time. A
repository that clones in 19 seconds took over an hour to analyse that way.

## Tests

```bash
python -m pytest -v
```

## Limits of this tool

Veriquill supports a human decision and never makes one. It does not
auto-reject, does not auto-hire, does not infer protected attributes, and does
not scrape any source that prohibits it. A red flag is a question for the
recruiter, not proof of wrongdoing: bulk-dump history, for instance, looks
identical whether a codebase was fabricated or simply developed locally and
imported once.

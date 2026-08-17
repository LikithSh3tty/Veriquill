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
blocking human review gate and an append-only override log (M4); and the
evaluation harness measuring the checks against hand-labelled cases (M5).

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

# Veriquill

Proof over polish. Evidence-first hiring intelligence that verifies a portfolio
before it ranks anyone.

Veriquill answers two questions generic screening tools skip: is this work
genuinely the candidate's own iterative effort, and is the code any good.
Every finding it emits cites the commit, file, or line that produced it.

## Status

Milestone M1 (GitHub engines) is implemented: repository ingestion,
deterministic provenance and authenticity checks, and static code evaluation.
Findings are advisory. Veriquill never auto-rejects, never auto-hires, and
never treats a flag as proof of wrongdoing.

M1 makes no LLM calls. Every finding is deterministic and reproducible.

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
returns it.

## Rate limits

Veriquill requires a GitHub token and refuses to run without one:
unauthenticated REST allows 60 requests per hour, authenticated allows 5,000.
Commit history and file contents come from `git clone --filter=blob:none`,
which is not billed against that quota, so REST use stays at roughly two to
five calls per candidate. Those calls are ETag-cached, and a 304 response is
free, so repeat runs on the same candidate cost almost nothing.

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

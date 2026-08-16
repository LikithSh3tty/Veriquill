# Veriquill

Proof over polish. Evidence-first hiring intelligence that verifies a portfolio
before it ranks anyone.

Veriquill answers two questions generic screening tools skip: is this work
genuinely the candidate's own iterative effort, and is the code any good.
Every finding it emits cites the commit, file, or line that produced it.

## Status

Milestone M1 (GitHub engines) is under construction: repository ingestion,
deterministic provenance and authenticity checks, and static code evaluation.
Findings are advisory. Veriquill never auto-rejects, never auto-hires, and
never treats a flag as proof of wrongdoing.

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

## Tests

```bash
python -m pytest -v
```

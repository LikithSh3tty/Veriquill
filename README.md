<div align="center">

# Veriquill

**Proof over polish. Every claim about a candidate cites the commit that produced it.**

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Typer](https://img.shields.io/badge/Typer-CLI-2E8B57?logo=typer&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?logo=sqlalchemy&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6?logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-6-646CFF?logo=vite&logoColor=white)
![Claude](https://img.shields.io/badge/Claude-optional-D97757?logo=anthropic&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-single%20container-2496ED?logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/tests-438%20Python%20%2B%20Vitest-brightgreen)

</div>

A hiring tool that checks the work before it ranks the person. You give it a GitHub
handle — optionally a résumé and a LinkedIn export too — and it clones the portfolio,
reads the real commit history, runs static analysis over the authored code, matches
what the documents claim against what the repositories show, and writes a dossier
where every single finding points at a commit, a file, or a line.

It answers the two questions generic screening tools skip: **is this work genuinely
this candidate's own iterative effort**, and **is the code any good**. A bulk dump
with no development history, a fork presented as original work, a résumé claiming
five years of Django against three commits of it — those are the things it is built
to notice.

The part I care most about is what it refuses to do. No model sits on the provenance,
code-evaluation, or ranking path: those are deterministic and reproducible, and the
same input yields the same dossier every time. Nothing is exported until a named human
approves it. Thin evidence widens a confidence band, it never lowers a score, so a
candidate with private repositories reads as *we could not tell*, not *weak*. And a
red flag is a question for the recruiter, never proof of wrongdoing — bulk-dump history
looks identical whether a codebase was fabricated or simply developed locally and
imported once.

## What it does

- **Verifies provenance deterministically** — commit cadence, bulk dumps with no
  development history, forks presented as original work, template and dependency
  inflation, cross-profile duplication, and whether the candidate actually authored
  the commits they are being credited for.
- **Evaluates code by static analysis** — cyclomatic complexity, security hygiene,
  lint compliance, dead modules nothing imports, and test quality measured by
  assertion meaningfulness rather than test count. Python is analysed in depth;
  other languages are detected, counted, and the output says so explicitly.
- **Reconciles documents against evidence** — résumé and LinkedIn claims are extracted,
  matched to repositories, and marked corroborated, uncorroborated, or contradicted,
  with the evidence attached either way.
- **Ranks a cohort against a rubric** you weight over six fixed dimensions —
  authenticity, code quality, claim corroboration, test quality, security, breadth —
  reading only stored dossiers, with no network call and no LLM.
- **Blocks export behind a human gate.** Dismissals and band overrides never edit the
  machine result; they are recorded beside it with the actor and the reason, in an
  append-only audit log that replays to any state the comparison has held.
- **Audits itself for bias**, redacts protected attributes at the door, and generates
  a disclosure pack from the running code rather than from a hand-maintained document.
- **Ships as one container** serving the API, the CLI, and the React review dashboard
  behind a single origin.

## How a run is wired

Every finding carries at least one evidence reference. That is a structural guarantee
rather than a convention: a `Finding` with empty evidence cannot be constructed.

```
   handle + optional résumé / LinkedIn
                 │
                 ▼
        ┌─────────────────┐
        │  intake         │  protected attributes redacted before parsing
        └────────┬────────┘
                 ▼
        ┌─────────────────┐
        │  relevance      │  ranks repos from metadata GitHub already returned
        └────────┬────────┘   (nothing cloned to decide whether to clone it)
                 ▼
        ┌─────────────────┐
        │  ephemeral      │  full clone — history needs blobs
        │  clone          │
        └────────┬────────┘
       ┌─────────┴─────────┐
       ▼                   ▼
┌────────────┐      ┌────────────┐
│ provenance │      │  codeeval  │      ┌────────────┐
│            │      │            │      │   claims   │
│ cadence    │      │ complexity │      │            │
│ bulk dump  │      │ security   │      │ résumé     │
│ fork       │      │ style      │      │ linkedin   │
│ inflation  │      │ tests      │      └──────┬─────┘
│ duplication│      │ structure  │             │
│ authorship │      │ (+reviewer)│             │
└──────┬─────┘      └──────┬─────┘             │
       └────────┬──────────┴───────────────────┘
                ▼
        ┌─────────────────┐
        │  reconcile      │  claims ↔ evidence
        └────────┬────────┘
                 ▼
        ┌─────────────────┐
        │  dossier        │  stored; every finding cites its evidence
        └────────┬────────┘
                 ▼
        ┌─────────────────┐
        │  rank           │  rubric weights, confidence bands, no LLM
        └────────┬────────┘
                 ▼
        ┌─────────────────┐
        │  human review   │  ← export blocked until a named human approves
        └────────┬────────┘
                 ▼
          export + audit log + fairness report
```

**Design review is the one optional model call**, off by default. Set
`VERIQUILL_CODE_REVIEW_ENABLED=true` and Claude phrases the judgment static analysis
cannot reach — tangled responsibilities, decisions duplicated across modules, error
handling that hides failures. It runs under hard constraints: every observation must
quote a line that appears verbatim at the file and line it cites or it is discarded;
severity is capped at medium and confidence at 0.5, so a judgment can never outrank
something that was measured; it is told not to report metrics, because every number in
the dossier comes from static analysis; and it only ever sees authored code, never
vendored trees. With the setting off, or with no credentials resolved, the pipeline is
fully deterministic. (A second optional call refines the *phrasing* of claims already
extracted from the candidate's own documents. It invents nothing.)

## Project layout

```
Veriquill/
├── veriquill/
│   ├── pipeline.py           # fan-out over repos; one failure never fails the run
│   ├── intake.py             # redaction + document intake
│   ├── relevance.py          # which repos get cloned, and why
│   ├── github/               # client, ETag cache, ephemeral clone, history reader
│   ├── provenance/           # cadence, bulk_dump, fork_origin, inflation,
│   │                         #   duplication, contribution — all deterministic
│   ├── codeeval/             # complexity, security, style, tests, structure,
│   │                         #   detect (+ reviewer: the optional LLM pass)
│   ├── claims/               # résumé + LinkedIn extraction, refine
│   ├── reconcile/            # matcher, evidence, engine
│   ├── rank/                 # dimensions, score, compare
│   ├── review.py             # the human gate + append-only audit log
│   ├── fairness/             # audit, signals, disclosure pack
│   ├── eval/                 # harness, ground truth, metrics
│   ├── api/                  # FastAPI app; also serves the built UI
│   └── cli.py                # the `veriquill` command
├── ui/
│   └── src/
│       ├── Landing.tsx       # public page
│       ├── App.tsx           # review screen
│       ├── api.ts            # typed API client
│       └── components/       # BandAxis, DimensionTable, ReviewPanel,
│                             #   CohortPicker, AddCandidate, JobDescription
├── tests/                    # 438 tests
├── Dockerfile                # one image: API + CLI + built interface
├── DESIGN.md                 # design decisions for both surfaces
└── PRODUCT.md                # product truth
```

## Running it locally

You'll need Python 3.11+, Node 18+, Git on PATH, and a GitHub personal access token.

### 1. The engine

```bash
python -m venv .venv
.venv/Scripts/activate      # Windows; source .venv/bin/activate elsewhere
pip install -e ".[dev]"
cp .env.example .env        # then edit .env and add your token
```

```bash
veriquill analyse octocat --output dossier.json
python -m pytest -v
```

### 2. The API

```bash
uvicorn veriquill.api.main:app --reload
```

**Run it from the repository root.** Settings read `.env` relative to the working
directory, so starting `uvicorn` elsewhere loses the token and every analysis fails
with `MissingTokenError`.

### 3. The dashboard

In a second terminal:

```bash
cd ui && npm install && npm run dev
```

`http://localhost:5173/` is the public page; the review screen is at
`http://localhost:5173/review.html?comparison=1`. The dev server proxies `/api` to
port 8000. Note that Vite binds IPv6 `localhost`, not `127.0.0.1`.

```bash
npm test        # component + API-client tests
npm run build   # production bundle
npm run lint    # typecheck
```

## Using it

### Adding candidates

From the review screen, open **Add candidates and rank a cohort**, enter a GitHub
username, and optionally attach a résumé or a LinkedIn export. Analysis runs as a
background job because cloning a portfolio takes a minute or two; the form reports
progress and says so up front. Once stored, tick the candidates and rank them — the
whole loop stays in the browser. Uploaded documents are read once and deleted.

The equivalent from a terminal:

```bash
veriquill dossier alice
veriquill dossier bob --resume ./bob-cv.pdf --linkedin ./bob-export.csv
```

Either route produces the same stored dossier.

### Comparing them

```bash
veriquill rubric-add rubric.json
veriquill rank --rubric backend-hire --candidate alice --candidate bob
veriquill review-show 1
veriquill review-flag 1 --candidate bob --flag 3f2a91c40b7e \
  --action dismiss --actor "you@example.com" --reason "employer-owned import"
veriquill review-approve 1 --actor "you@example.com"
veriquill export-comparison 1 --output comparison.json
veriquill audit 1
veriquill fairness-report 1 --output fairness.json
```

A rubric weights six fixed dimensions. Unlisted ones take their default weight; an
unknown dimension name is refused rather than ignored. **A comparison cannot be
exported until a named human approves it**, and an approval covers exactly the revision
it saw — any later review action bumps the revision and reopens the gate.

Every candidate's confidence band is drawn on one shared axis in the dashboard, so
where two bands overlap you can see that the evidence does not separate those
candidates; tied candidates are bracketed together rather than listed in an order that
would imply a difference. Colour marks who said what — the machine's numbers in ink,
every human dismissal or override beside them in blue.

## The API

Every endpoint answers both at the root and under `/api`. The root is the documented
surface; the `/api` copy exists so the interface and the API can share one origin.

| Method | Path | What it does |
| --- | --- | --- |
| `POST` | `/analyse` | start a run for a handle |
| `GET` | `/runs/{run_id}` | fetch a run |
| `POST` | `/candidates` | queue a candidate (with optional documents) |
| `GET` | `/candidates` · `/candidates/jobs/{id}` | list candidates; poll a background job |
| `POST` | `/rubrics` · `/rubrics/from-job-description` | define a rubric, or derive one from a posting |
| `POST` | `/comparisons` | rank a cohort |
| `GET` | `/comparisons/{id}` · `/dossiers` · `/audit` · `/export` | read a comparison, its dossiers, its log, its export |
| `POST` | `/comparisons/{id}/review` · `/approve` | record a review action; open the export gate |
| `GET` | `/health` | liveness |

```bash
curl -X POST localhost:8000/analyse -H 'content-type: application/json' \
     -d '{"handle": "octocat"}'
```

## Large accounts

An account with more than 20 repositories is read in part: Veriquill clones the 5 most
relevant to the posting and names the rest as unread. Both numbers are configurable
(`VERIQUILL_RELEVANCE_THRESHOLD`, `VERIQUILL_RELEVANCE_LIMIT`), and a smaller account is
always read in full.

Relevance is decided from metadata GitHub already returned — language named in the
posting, matching topics, matching description terms, size, recency, fork status — so
nothing is cloned in order to decide whether to clone it. Every selected repository
records why it was chosen, and every skipped one is named.

**Skipping is coverage, never a finding.** The dossier counts the whole account, so
reading 5 of 21 lowers coverage and widens the confidence band. A partial look must
never read as a full one, and a candidate is never marked down for work the tool chose
not to read. The ordering among equally relevant repositories falls back to size and
recency, which is a proxy rather than a judgment of merit.

## Rate limits

Veriquill requires a GitHub token and refuses to run without one: unauthenticated REST
allows 60 requests per hour, authenticated allows 5,000.

Commit history and file contents come from `git clone`, which runs over git transport
and is not billed against that quota. REST is used only to resolve the candidate and
list their repositories: an eight-repository account costs exactly **two** REST calls.
Those calls are ETag-cached and a 304 response is free, so repeat runs on the same
candidate cost almost nothing.

Clones are deliberately complete rather than `--filter=blob:none`. Partial clones look
cheaper and are much worse here: provenance reads history with `git log --numstat`,
which diffs every commit and therefore needs blob contents, so git back-fills them from
the remote one round trip at a time. A repository that clones in 19 seconds took over
an hour to analyse that way.

## Fairness and compliance

Veriquill treats itself as an automated employment decision tool and ships the artifacts
that position demands.

**Protected attributes are removed at the door.** Résumés in many countries state date of
birth, marital status, nationality, religion, caste, blood group, or attach a photograph.
Those fields are detected by label and redacted before parsing, before any model call,
and before anything is stored, so they never reach a claim, a score, a log, or the
recruiter's screen. The dossier records that a field was present and removed, never what
it contained.

**The bias audit runs with or without group labels.**

```bash
veriquill fairness-report 1 --groups groups.json --top-k 3 --format markdown -o pack.md
```

Veriquill never infers a protected attribute, so selection-rate arithmetic needs group
labels supplied from your own records (`{"alice": "A", "bob": "B"}`). Given them, it
reports selection rate per group, the impact ratio against the four-fifths rule, and
per-check flag rates — because an ordering can look even while the reasons behind it do
not. Without labels it still audits what needs no protected data at all: how evenly
evidence could be gathered across the cohort. That is the most likely route to disparate
impact in this design, since a portfolio in a language Veriquill does not analyse in
depth, or one held in private repositories, yields less evidence through no fault of the
candidate.

**The disclosure pack is generated from the running code**, not maintained by hand:
measured dimensions come from the rubric and excluded attributes from the scanner itself,
so neither can drift out of date. It is a self-audit artifact — jurisdictions such as New
York City require an independent bias audit, and nothing here replaces one.

## Deployment

One container serves the API, the CLI, and the built interface behind a single origin, so
the browser's `/api` calls never leave it.

```bash
docker build -t veriquill .
docker run -p 8000:8000 \
  -e VERIQUILL_GITHUB_TOKEN=ghp_yourtoken \
  -v veriquill-data:/data \
  veriquill
```

The public page is then at `http://localhost:8000/`, the review screen at
`http://localhost:8000/review.html?comparison=1`.

**Mount a volume on `/data`.** Clones, caches, and the SQLite database live there; a
container that loses it loses every stored dossier. Git is installed in the image because
the provenance engine reads real commit history out of a clone.

Without Docker, build the interface once and point the API at it:

```bash
cd ui && npm ci && npm run build && cd ..
uvicorn veriquill.api.main:app --host 0.0.0.0 --port 8000
```

`VERIQUILL_UI_DIST` sets where the built files are read from (default `ui/dist`). If they
are absent the API starts anyway and serves no pages, which is what the tests and the CLI
use.

## A note on security

**There is no authentication in front of any of this.** `--actor` is whatever the caller
types, and every endpoint is open. Until that changes, run it somewhere only the hiring
team can reach — a deployment that matters must supply an authenticated identity, because
the audit log is only as trustworthy as the name written into it.

What is in place is the floor beneath authentication, not a replacement for it. Request
bodies are capped before anything reads them, including chunked bodies that declare no
length; uploads are read in bounded chunks so an oversized file costs one chunk and a
refusal rather than the memory it claimed; job descriptions are length-capped; and each
client IP gets a request budget, a small one on the endpoints that clone a portfolio and
a larger one on ordinary reads. All four are tunable, and setting a limit to `0` turns it
off for a deployment that already has its own gateway.

| Setting | Default | What it bounds |
| --- | --- | --- |
| `VERIQUILL_API_MAX_REQUEST_BYTES` | 6 MB | any request body |
| `VERIQUILL_API_RATE_LIMIT` | 60/min | ordinary reads and writes, per client |
| `VERIQUILL_API_ANALYSIS_RATE_LIMIT` | 10/min | endpoints that start a clone, per client |
| `VERIQUILL_MAX_JOB_DESCRIPTION_CHARS` | 20,000 | a posting handed to the rubric deriver |

The budget is per process and keyed on the socket address, not on a forwarded header —
a header is caller-supplied and would let anyone spend anyone else's budget. Behind a
trusted proxy that means the proxy, which is a real limitation and the reason this is a
floor rather than a defence.

On the data side: uploaded documents are read once and deleted, clones are ephemeral,
protected attributes are redacted before anything touches disk, and the optional model
calls only ever see authored code and the candidate's own documents.

## What's implemented

Repository ingestion, deterministic provenance and authenticity checks, and static code
evaluation (M1); résumé and LinkedIn claim workers (M2); reconciliation and the candidate
dossier (M3); rubric-weighted ranking with a blocking human review gate and an
append-only override log (M4); the evaluation harness measuring the checks against
hand-labelled cases and the ranking against reference orderings (M5); and the fairness
controls, bias audit, and disclosure pack (M6).

## Things I'd add next

- Deep static analysis for a second language, so a non-Python portfolio stops costing
  the candidate coverage.
- Real authentication in front of the API, so `--actor` means something and the audit
  log can be trusted on its own.
- Incremental re-analysis: re-read only what changed since the last dossier instead of
  re-cloning a portfolio.
- End-to-end tests through the dashboard, not just component and API-client tests.

## Limits of this tool

Veriquill supports a human decision and never makes one. It does not auto-reject, does
not auto-hire, does not infer protected attributes, and does not scrape any source that
prohibits it. A red flag is a question for the recruiter, not proof of wrongdoing.

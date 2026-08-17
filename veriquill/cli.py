"""Command line entry point."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from pathlib import Path

import typer

from veriquill.claims.engine import collect_claims
from veriquill.config import get_settings
from veriquill.db import init_db, make_engine, make_session_factory
from veriquill.dossier import build_dossier
from veriquill.eval.harness import evaluate as run_evaluation
from veriquill.pipeline import analyse_candidate
from veriquill.reconcile.engine import reconcile
from veriquill.review import ReviewError, audit_log, effective_result, export_payload, record_action
from veriquill.review import approve as approve_comparison
from veriquill.rubric import Rubric, RubricError
from veriquill.store import (
    StoreError,
    create_comparison,
    get_comparison,
    list_rubrics,
    save_dossier,
    save_rubric,
)

app = typer.Typer(help="Veriquill: evidence-first portfolio verification.")


@app.callback()
def main() -> None:
    """Keep `veriquill` a command group.

    With a single registered command Typer collapses the group and swallows the
    subcommand name as the first argument, so `veriquill analyse <handle>` would
    silently read "analyse" as the handle.
    """


@app.command()
def analyse(
    handle: str = typer.Argument(..., help="GitHub handle to analyse."),
    output: Path = typer.Option(None, "--output", "-o", help="Write the JSON summary here."),
) -> None:
    """Analyse a candidate's public GitHub portfolio.

    Findings are advisory. Veriquill never auto-rejects and never auto-hires.
    """
    settings = get_settings()
    summary = asyncio.run(analyse_candidate(handle, settings))
    payload = json.dumps(summary.to_dict(), indent=2)

    if output is not None:
        output.write_text(payload, encoding="utf-8")
        typer.echo(f"wrote {output}")
    else:
        typer.echo(payload)


@app.command()
def claims(
    resume: Path = typer.Option(None, "--resume", help="Resume file (.pdf/.docx/.txt/.md)."),
    linkedin: Path = typer.Option(
        None,
        "--linkedin",
        help="LinkedIn data export (.csv) or manual entry (.json). Never a URL.",
    ),
    output: Path = typer.Option(None, "--output", "-o", help="Write the JSON claims here."),
) -> None:
    """Extract the claims a candidate makes about themselves.

    Claims are statements, not facts. They are only meaningful once reconciled
    against evidence, which is the next milestone.
    """
    if resume is None and linkedin is None:
        raise typer.BadParameter("provide --resume, --linkedin, or both")

    settings = get_settings()
    result = collect_claims(settings, resume=resume, linkedin=linkedin)
    payload = json.dumps(result.to_dict(), indent=2)

    if output is not None:
        output.write_text(payload, encoding="utf-8")
        typer.echo(f"wrote {output}")
    else:
        typer.echo(payload)

    for error in result.errors:
        typer.echo(f"warning: {error}", err=True)


@app.command()
def dossier(
    handle: str = typer.Argument(..., help="GitHub handle to analyse."),
    resume: Path = typer.Option(None, "--resume", help="Resume file (.pdf/.docx/.txt/.md)."),
    linkedin: Path = typer.Option(
        None, "--linkedin", help="LinkedIn data export (.csv) or manual entry (.json)."
    ),
    output: Path = typer.Option(None, "--output", "-o", help="Write the JSON dossier here."),
) -> None:
    """Reconcile a candidate's claims against their public evidence.

    Produces the consolidated summary: verified strengths, every red flag with
    its evidence, the claim-versus-evidence table, and what to ask in an
    interview. It is advisory. It is not a hiring decision.
    """
    settings = get_settings()

    summary = asyncio.run(analyse_candidate(handle, settings))
    claim_set = collect_claims(settings, resume=resume, linkedin=linkedin)
    evidence = [r.evidence for r in summary.repositories if r.evidence is not None]

    reconciliations = reconcile(claim_set.claims, evidence)
    report = build_dossier(handle, summary.repositories, reconciliations)
    report["claims_examined"] = len(claim_set.claims)
    report["claim_errors"] = claim_set.errors

    # Stored as well as printed: ranking reads dossiers from the database, and a
    # dossier that only ever existed on stdout could never be compared.
    with _session() as session:
        record = save_dossier(session, report)
    typer.echo(f"stored dossier {record.id} for {handle}", err=True)

    payload = json.dumps(report, indent=2)
    if output is not None:
        output.write_text(payload, encoding="utf-8")
        typer.echo(f"wrote {output}")
    else:
        typer.echo(payload)


@app.command()
def evaluate(
    output: Path = typer.Option(None, "--output", "-o", help="Write the JSON report here."),
) -> None:
    """Measure the checks against hand-labelled cases.

    Reports precision and recall per check, plus whether stated confidence is
    earned. Needs no GitHub token and makes no network calls.
    """
    settings = get_settings()
    report = run_evaluation(settings)

    payload = json.dumps(report, indent=2)
    if output is not None:
        output.write_text(payload, encoding="utf-8")
        typer.echo(f"wrote {output}")

    overall = report["overall"]
    typer.echo(
        f"{report['cases_passed']}/{report['cases_run']} cases behaved as labelled | "
        f"precision {overall['precision']:.2f} recall {overall['recall']:.2f}"
    )
    if report["false_alarms_on_clean_cases"]:
        typer.echo(
            "false alarms: " + ", ".join(report["false_alarms_on_clean_cases"]),
            err=True,
        )
        raise typer.Exit(code=1)


@contextmanager
def _session():
    """One short-lived session per command; the CLI is not a long-running process."""
    settings = get_settings()
    settings.ensure_dirs()
    engine = make_engine(settings.db_path)
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        yield session
        session.commit()


def _fail(message: str) -> None:
    typer.echo(message)
    raise typer.Exit(code=1)


@app.command()
def rubric_add(path: Path = typer.Argument(..., help="Rubric JSON file.")) -> None:
    """Store a recruiter rubric.

    Weights are normalised on load and the stored copy is versioned, so a
    comparison scored today stays reproducible after the rubric changes.
    """
    try:
        rubric = Rubric.load(path)
    except RubricError as exc:
        _fail(f"rubric refused: {exc}")

    with _session() as session:
        save_rubric(session, rubric)
    typer.echo(f"stored rubric {rubric.name!r} version {rubric.version}")


@app.command()
def dossier_import(
    path: Path = typer.Argument(..., help="A dossier JSON file written by `veriquill dossier`.")
) -> None:
    """Store an existing dossier file so it can be ranked.

    `veriquill dossier` stores what it builds. This exists for dossiers produced
    on another machine, or before this command existed.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"cannot read {path}: {exc}")

    with _session() as session:
        try:
            record = save_dossier(session, payload)
        except StoreError as exc:
            _fail(str(exc))
        typer.echo(f"stored dossier {record.id} for {record.candidate_handle}")


@app.command()
def rubric_list() -> None:
    """List the stored rubrics and their weights."""
    with _session() as session:
        for rubric in list_rubrics(session):
            weights = ", ".join(f"{k} {v:.2f}" for k, v in sorted(rubric.weights.items()))
            typer.echo(f"{rubric.name} v{rubric.version}: {weights}")


@app.command()
def rank(
    rubric: str = typer.Option(..., "--rubric", help="Name of a stored rubric."),
    candidate: list[str] = typer.Option(
        ..., "--candidate", help="Candidate handle; repeat for a cohort."
    ),
) -> None:
    """Rank stored dossiers against a rubric.

    The comparison is created pending review. Nothing can be exported until a
    named human approves it.
    """
    with _session() as session:
        try:
            comparison = create_comparison(session, rubric, list(candidate))
            result = effective_result(session, comparison)
        except StoreError as exc:
            _fail(f"cannot rank: {exc}")

        typer.echo(f"comparison {comparison.id} ({comparison.status})")
        for row in result["ranked"]:
            score = row["score"]
            typer.echo(
                f"  {row['rank']}. {row['handle']} "
                f"{score['score']:.2f} "
                f"[{score['band'][0]:.2f}-{score['band'][1]:.2f}] "
                f"confidence {score['confidence']}"
            )
        for row in result["unranked"]:
            typer.echo(f"  unranked: {row['handle']} - {row['reason']}")
        typer.echo(result["disclaimer"])


@app.command()
def review_show(comparison_id: int = typer.Argument(..., help="Comparison id.")) -> None:
    """Show a comparison with every flag id a reviewer can act on."""
    with _session() as session:
        try:
            comparison = get_comparison(session, comparison_id)
        except StoreError as exc:
            _fail(str(exc))

        result = effective_result(session, comparison)
        typer.echo(
            f"comparison {comparison.id}: {comparison.status} "
            f"(revision {comparison.revision})"
        )
        for entry in sorted(comparison.entries, key=lambda e: e.id):
            typer.echo(f"  {entry.candidate_handle}:")
            for flag in (entry.dossier.payload or {}).get("red_flag_register") or []:
                typer.echo(
                    f"    {flag['flag_id']} [{flag['severity']}] "
                    f"{flag['check_id']}: {flag['title']}"
                )
        for row in result["ranked"]:
            if row["human_band"]:
                typer.echo(f"  override: {row['handle']} -> {row['human_band']}")


@app.command()
def review_flag(
    comparison_id: int = typer.Argument(..., help="Comparison id."),
    candidate: str = typer.Option(..., "--candidate", help="Candidate handle."),
    flag: str = typer.Option(..., "--flag", help="flag_id from `review-show`."),
    action: str = typer.Option(..., "--action", help="dismiss or confirm."),
    actor: str = typer.Option(..., "--actor", help="Who is making this call."),
    reason: str = typer.Option(..., "--reason", help="Why. Recorded permanently."),
) -> None:
    """Dismiss or confirm one red flag.

    A dismissal removes the flag from the score and is recorded with the actor
    and the reason. The machine result is never edited.
    """
    if action not in ("dismiss", "confirm"):
        _fail("--action must be dismiss or confirm")

    with _session() as session:
        try:
            comparison = get_comparison(session, comparison_id)
            record_action(
                session,
                comparison,
                actor=actor,
                action=f"flag_{action}",
                candidate=candidate,
                target=flag,
                reason=reason,
            )
        except (StoreError, ReviewError) as exc:
            _fail(str(exc))
    typer.echo(f"recorded {action} of {flag} for {candidate}")


@app.command()
def review_band(
    comparison_id: int = typer.Argument(..., help="Comparison id."),
    candidate: str = typer.Option(..., "--candidate", help="Candidate handle."),
    band: str = typer.Option(..., "--band", help="The band this reviewer judges correct."),
    actor: str = typer.Option(..., "--actor", help="Who is making this call."),
    reason: str = typer.Option(..., "--reason", help="Why. Recorded permanently."),
) -> None:
    """Override the verdict band for one candidate.

    The machine band stays in the export next to the human one, with this reason.
    """
    with _session() as session:
        try:
            comparison = get_comparison(session, comparison_id)
            record_action(
                session,
                comparison,
                actor=actor,
                action="band_override",
                candidate=candidate,
                target=band,
                reason=reason,
            )
        except (StoreError, ReviewError) as exc:
            _fail(str(exc))
    typer.echo(f"recorded band override for {candidate}")


@app.command()
def review_approve(
    comparison_id: int = typer.Argument(..., help="Comparison id."),
    actor: str = typer.Option(..., "--actor", help="Who is approving."),
) -> None:
    """Approve a comparison so it can be exported.

    An approval covers exactly the revision it saw. Any later review action
    reopens the gate.
    """
    with _session() as session:
        try:
            comparison = get_comparison(session, comparison_id)
            approve_comparison(session, comparison, actor)
        except (StoreError, ReviewError) as exc:
            _fail(str(exc))
        typer.echo(f"comparison {comparison_id} approved at revision {comparison.revision}")


@app.command()
def export_comparison(
    comparison_id: int = typer.Argument(..., help="Comparison id."),
    output: Path = typer.Option(None, "--output", "-o", help="Write the JSON export here."),
) -> None:
    """Export an approved comparison, machine result and human overrides side by side."""
    with _session() as session:
        try:
            comparison = get_comparison(session, comparison_id)
            payload = export_payload(session, comparison)
        except (StoreError, ReviewError) as exc:
            _fail(str(exc))

    text = json.dumps(payload, indent=2)
    if output is not None:
        output.write_text(text, encoding="utf-8")
        typer.echo(f"wrote {output}")
    else:
        typer.echo(text)


@app.command()
def audit(comparison_id: int = typer.Argument(..., help="Comparison id.")) -> None:
    """Print every review action taken on a comparison, in order."""
    with _session() as session:
        try:
            comparison = get_comparison(session, comparison_id)
        except StoreError as exc:
            _fail(str(exc))
        for row in audit_log(session, comparison):
            typer.echo(
                f"{row['created_at']} r{row['revision']} {row['actor']} {row['action']} "
                f"{row['candidate'] or ''} {row['target'] or ''}: {row['reason']}"
            )


if __name__ == "__main__":
    app()

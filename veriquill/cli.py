"""Command line entry point."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from veriquill.claims.engine import collect_claims
from veriquill.config import get_settings
from veriquill.dossier import build_dossier
from veriquill.eval.harness import evaluate as run_evaluation
from veriquill.pipeline import analyse_candidate
from veriquill.reconcile.engine import reconcile

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


if __name__ == "__main__":
    app()

"""Command line entry point."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from veriquill.claims.engine import collect_claims
from veriquill.config import get_settings
from veriquill.pipeline import analyse_candidate

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


if __name__ == "__main__":
    app()

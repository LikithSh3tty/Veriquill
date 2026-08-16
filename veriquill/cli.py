"""Command line entry point."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

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


if __name__ == "__main__":
    app()

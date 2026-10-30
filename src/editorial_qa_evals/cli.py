"""Offline commands for deterministic editorial checks; labeling is browser-only."""

from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from editorial_qa_evals.deterministic import run_checks
from editorial_qa_evals.models import Entry

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Inspect entries with the offline deterministic checker."""


@app.command()
def check(entry_file: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """Print results. Exit 1 on check failures, 2 on invalid input."""
    try:
        entry = Entry.model_validate_json(entry_file.read_text())
    except (OSError, UnicodeError, ValidationError) as error:
        typer.echo(f"Invalid entry: {error}", err=True)
        raise typer.Exit(2) from error
    results = run_checks(entry)
    table = Table("Check", "Result", "Severity", "Evidence")
    for result in results:
        evidence = "\n".join(
            f"{e.location}, item "
            f"{e.item_number if e.item_number is not None else 'global'}: "
            f"{e.span!r} ({e.detail})"
            for e in result.evidence
        )
        table.add_row(result.check_id, result.result, result.severity or "", evidence)
    Console(markup=False, highlight=False).print(table)
    if any(result.result == "fail" for result in results):
        raise typer.Exit(1)


if __name__ == "__main__":
    app()

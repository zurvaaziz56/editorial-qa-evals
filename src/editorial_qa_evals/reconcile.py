"""Explicitly reconcile hidden fault metadata only after human labeling is complete."""

import json
import re
from pathlib import Path
from typing import Literal

import typer
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from editorial_qa_evals.fingerprints import entry_sha256
from editorial_qa_evals.models import Entry

app = typer.Typer(add_completion=False)


class FaultRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^syn-[0-9]{4,}$")
    entry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recipes: list[str]
    injected_faults: list[str]
    intended_verdict: Literal["READY", "REVISE", "MAJOR"]


def _records(path: Path) -> list[dict[str, object]]:
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"Expected an object on line {number}")
        records.append(value)
    if not records:
        raise ValueError("Input contains no records")
    return records


def reconcile_faults(faults_file: Path, entries_file: Path, out: Path) -> int:
    """Validate both full inputs before writing a new, explicitly selected file."""
    if out.resolve() in {faults_file.resolve(), entries_file.resolve()}:
        raise ValueError("Choose a new output path; source files must remain unchanged")
    if out.exists():
        raise ValueError("Output already exists; choose a new output path")
    public = _records(entries_file)
    entries = [Entry.model_validate(row) for row in public]
    hidden = [FaultRecord.model_validate(row) for row in _records(faults_file)]
    entry_ids = [entry.id for entry in entries]
    fault_ids = [record.id for record in hidden]
    if len(set(entry_ids)) != len(entry_ids) or len(set(fault_ids)) != len(fault_ids):
        raise ValueError("Duplicate IDs in entries or faults")
    if set(entry_ids) != set(fault_ids):
        raise ValueError("Entries and fault records must contain exactly the same IDs")
    check_ids = {f"C{i}" for i in range(1, 14)}
    judgment_ids = {f"J{i}" for i in range(1, 8)}
    for entry in entries:
        human = entry.human
        if (
            human is None
            or set(human.checks) != check_ids
            or set(human.judgment) != judgment_ids
        ):
            raise ValueError("Human labeling must be complete before reconciliation")
    by_id = {record.id: record for record in hidden}
    output = []
    for row, entry in zip(public, entries, strict=True):
        record = by_id[entry.id]
        if record.entry_sha256 != entry_sha256(entry):
            raise ValueError("Fault metadata does not match the entry content")
        if any(
            not re.fullmatch(r"(?:C(?:[1-9]|1[0-3])|J[1-7]|P(?:[1-9]|10))", code)
            for code in record.injected_faults
        ):
            raise ValueError("Unknown injected check or pattern ID")
        if "injected_faults" in row:
            raise ValueError("Entries are already reconciled")
        output.append({**row, "injected_faults": record.injected_faults})
    serialized = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects against an output appearing after validation.
    with out.open("x", encoding="utf-8") as handle:
        handle.write(serialized)
    return len(output)


@app.command()
def main(
    faults_file: Path = typer.Argument(..., exists=True, dir_okay=False),
    entries: Path = typer.Option(
        Path("data/golden/synthetic.jsonl"), exists=True, dir_okay=False
    ),
    out: Path = typer.Option(
        ..., help="New output file; originals are never overwritten."
    ),
) -> None:
    """After human labeling, merge faults by ID into a new JSONL file."""
    try:
        count = reconcile_faults(faults_file, entries, out)
    except (OSError, UnicodeError, ValueError, ValidationError) as error:
        typer.echo(f"Cannot reconcile: {error}", err=True)
        raise typer.Exit(2) from error
    typer.echo(f"Reconciled {count} labeled entries into {out}")

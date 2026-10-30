"""Fault metadata stays separate until explicitly reconciled after labeling."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from editorial_qa_evals.fingerprints import entry_sha256
from editorial_qa_evals.models import Entry
from editorial_qa_evals.reconcile import app, reconcile_faults


@pytest.fixture()
def inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    entry = json.loads(
        (Path(__file__).parent / "fixtures/clean_entry.json").read_text()
    )
    entry["human"] = {
        "checks": {f"C{i}": "pass" for i in range(1, 14)},
        "judgment": {f"J{i}": "pass" for i in range(1, 8)},
        "routing": "none",
        "verdict": "READY",
        "notes": "",
        "labeled_at": "2026-01-01T00:00:00Z",
        "labeler": "r1",
        "pass_number": 1,
    }
    entries = tmp_path / "entries.jsonl"
    entries.write_text(json.dumps(entry) + "\n")
    faults = tmp_path / "faults.jsonl"
    faults.write_text(
        json.dumps(
            {
                "id": entry["id"],
                "entry_sha256": entry_sha256(Entry.model_validate(entry)),
                "recipes": ["em_dash"],
                "injected_faults": ["C8"],
                "intended_verdict": "REVISE",
            }
        )
        + "\n"
    )
    return faults, entries, tmp_path / "reconciled.jsonl"


def test_explicit_reconciliation_preserves_sources(
    inputs: tuple[Path, Path, Path],
) -> None:
    faults, entries, out = inputs
    before = entries.read_bytes()
    assert reconcile_faults(faults, entries, out) == 1
    assert entries.read_bytes() == before
    row = json.loads(out.read_text())
    assert row["injected_faults"] == ["C8"]
    assert "intended_verdict" not in row
    assert "recipes" not in row
    assert row["human"]["verdict"] == "READY"


@pytest.mark.parametrize(
    "problem",
    [
        "duplicate_entries",
        "duplicate_faults",
        "missing_id",
        "unlabeled",
        "partially_labeled",
        "mismatched_content",
        "invalid_fingerprint",
        "unknown_check",
        "already_reconciled",
        "invalid_json",
        "non_object",
        "empty",
    ],
)
def test_invalid_inputs_never_write(
    inputs: tuple[Path, Path, Path], problem: str
) -> None:
    faults, entries, out = inputs
    if problem == "duplicate_entries":
        entries.write_text(entries.read_text() * 2)
    elif problem == "duplicate_faults":
        faults.write_text(faults.read_text() * 2)
    elif problem == "missing_id":
        row = json.loads(faults.read_text())
        row["id"] = "syn-9999"
        faults.write_text(json.dumps(row))
    elif problem == "unlabeled":
        row = json.loads(entries.read_text())
        row.pop("human")
        entries.write_text(json.dumps(row))
    elif problem == "partially_labeled":
        row = json.loads(entries.read_text())
        row["human"]["checks"].pop("C13")
        entries.write_text(json.dumps(row))
    elif problem == "mismatched_content":
        row = json.loads(entries.read_text())
        row["body"] += " A changed sentence."
        entries.write_text(json.dumps(row))
    elif problem == "invalid_fingerprint":
        row = json.loads(faults.read_text())
        row["entry_sha256"] = "not a hash"
        faults.write_text(json.dumps(row))
    elif problem == "unknown_check":
        row = json.loads(faults.read_text())
        row["injected_faults"] = ["C99"]
        faults.write_text(json.dumps(row))
    elif problem == "already_reconciled":
        row = json.loads(entries.read_text())
        row["injected_faults"] = []
        entries.write_text(json.dumps(row))
    elif problem == "invalid_json":
        faults.write_text("not json")
    elif problem == "non_object":
        faults.write_text("[]")
    elif problem == "empty":
        faults.write_text("")
    with pytest.raises(ValueError):
        reconcile_faults(faults, entries, out)
    assert not out.exists()


def test_output_cannot_overwrite(inputs: tuple[Path, Path, Path]) -> None:
    faults, entries, out = inputs
    with pytest.raises(ValueError, match="source files"):
        reconcile_faults(faults, entries, entries)
    out.write_text("Existing work")
    with pytest.raises(ValueError, match="already exists"):
        reconcile_faults(faults, entries, out)
    assert out.read_text() == "Existing work"


def test_cli(inputs: tuple[Path, Path, Path]) -> None:
    faults, entries, out = inputs
    result = CliRunner().invoke(
        app, [str(faults), "--entries", str(entries), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "Reconciled 1" in result.output
    result = CliRunner().invoke(
        app, [str(faults), "--entries", str(entries), "--out", str(out)]
    )
    assert result.exit_code == 2


def test_fingerprint_excludes_labels_and_faults(
    inputs: tuple[Path, Path, Path],
) -> None:
    _, entries, _ = inputs
    entry = Entry.model_validate(json.loads(entries.read_text()))
    original = entry_sha256(entry)
    assert len(original) == 64
    entry.human = None
    assert entry_sha256(entry) == original
    entry.injected_faults = ["C8"]
    assert entry_sha256(entry) == original
    entry.body += " Changed content."
    assert entry_sha256(entry) != original

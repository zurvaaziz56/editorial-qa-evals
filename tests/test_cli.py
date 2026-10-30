"""Exercise the actual offline command, including exit codes and input errors."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from editorial_qa_evals.cli import app

CLEAN = Path(__file__).parent / "fixtures/clean_entry.json"


def test_module_command() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "editorial_qa_evals.cli", "check", str(CLEAN)],
        capture_output=True,
        text=True,
        env={**os.environ, "COLUMNS": "160", "NO_COLOR": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert all(check in result.stdout for check in ["C1", "C12", "J2", "J4"])
    assert "pass" in result.stdout
    assert "na" in result.stdout


def test_failed_check_is_printed(tmp_path: Path) -> None:
    payload = json.loads(CLEAN.read_text())
    payload["body"] = payload["body"].replace("A steady rhythm", "A steady—rhythm", 1)
    path = tmp_path / "entry.json"
    path.write_text(json.dumps(payload))
    result = CliRunner().invoke(app, ["check", str(path)], terminal_width=200)
    assert result.exit_code == 1
    assert "C8" in result.stdout
    assert "MECHANICAL" in result.stdout
    assert "item 1" in result.stdout
    assert "—" in result.stdout


@pytest.mark.parametrize("content", ["not json", '{"body": "Rest."}', b"\xff"])
def test_invalid_input(tmp_path: Path, content: str | bytes) -> None:
    path = tmp_path / "entry.json"
    path.write_bytes(content.encode() if isinstance(content, str) else content)
    result = CliRunner().invoke(app, ["check", str(path)])
    assert result.exit_code == 2
    assert "Invalid entry" in result.output


def test_missing_file(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["check", str(tmp_path / "absent.json")])
    assert result.exit_code == 2

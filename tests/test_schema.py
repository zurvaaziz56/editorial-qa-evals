"""Smoke test for the public entry schema and its generated artifact."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from editorial_qa_evals.models import Entry


def test_entry_schema() -> None:
    schema = json.loads(
        (
            Path(__file__).resolve().parents[1] / "data/schema/entry.schema.json"
        ).read_text()
    )
    assert schema == Entry.model_json_schema()
    Draft202012Validator.check_schema(schema)
    payload = {
        "id": "syn-0001",
        "source": "synthetic",
        "piece_type": "qa",
        "region": "UK",
        "task_name": "Reviewer explains rest habits",
        "brief": {
            "tips": ["Keep a regular bedtime"],
            "hook": "Rest habits",
            "tone": "Accessible and precise",
            "expert": {"credential": "Reviewer", "specialism": "Rest habits"},
        },
        "approved_labels": [],
        "body": "What helps? A regular bedtime.",
        "questions": ["What helps?"],
        "answers": ["A regular bedtime."],
        "human": {
            "checks": {"C5": "pass", "C1": "na"},
            "judgment": {"J7": "pass"},
            "routing": "none",
            "verdict": "READY",
            "notes": "",
            "labeled_at": "2026-01-01T00:00:00Z",
            "labeler": "r1",
            "pass_number": 1,
        },
    }
    entry = Entry.model_validate(payload)
    assert entry.id == "syn-0001"
    assert entry.injected_faults is None
    validator = Draft202012Validator(schema)
    validator.validate(payload)
    invalid = {**payload, "region": "invalid"}
    with pytest.raises(ValidationError):
        Entry.model_validate(invalid)
    assert not validator.is_valid(invalid)

"""Clean-draft repairs preserve validation boundaries and record literal changes."""

import copy
from typing import Any

import pytest

from editorial_qa_evals.draft_normalization import normalize_clean_draft


def draft(
    title: str, paragraph: str = "A fictional routine helps. Quiet pauses matter."
) -> dict[str, Any]:
    return {
        "items": [
            {
                "title": title,
                "question": "What supports rest?",
                "paragraphs": [paragraph],
            }
        ]
    }


def test_normalization_copies_input_and_logs_each_change() -> None:
    original = draft(
        "sleep‑friendly ROUTINES!",
        "A sleep‐friendly routine helps. Quiet pauses matter.",
    )
    before = copy.deepcopy(original)
    normalized, changes = normalize_clean_draft(original, [])
    assert original == before
    assert normalized["items"][0]["title"] == "Sleep-friendly routines"
    assert normalized["items"][0]["paragraphs"] == [
        "A sleep-friendly routine helps. Quiet pauses matter."
    ]
    assert [(change["path"], change["operation"]) for change in changes] == [
        ("items.0.title", "word_hyphen"),
        ("items.0.title", "title_punctuation"),
        ("items.0.title", "sentence_case"),
        ("items.0.paragraphs.0", "word_hyphen"),
    ]
    assert changes[0]["before"] == "sleep‑friendly ROUTINES!"
    assert changes[0]["after"] == "sleep-friendly ROUTINES!"
    assert all(change["before"] != change["after"] for change in changes)


@pytest.mark.parametrize(
    "title,expected",
    [
        ("nhs rest habits.", "NHS rest habits"),
        ("a MEDICARE pause?!", "A Medicare pause"),
        ("rest in the uk…", "Rest in the UK"),
        ("nhsless routines!", "Nhsless routines"),
        ("mum and mom routines:", "Mum and Mom routines"),
        ("reviewer role morning ROUTINES;", "Reviewer Role morning routines"),
        ("reviewer roleless routines", "Reviewer roleless routines"),
    ],
)
def test_sentence_case_and_full_allowlisted_names(title: str, expected: str) -> None:
    result, _ = normalize_clean_draft(
        draft(title), ["NHS", "UK", "Medicare", "Mum", "Mom", "Reviewer Role", "Role"]
    )
    assert result["items"][0]["title"] == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("sleep‑friendly", "sleep-friendly"),
        ("sleep‐friendly", "sleep-friendly"),
        ("café‑rest", "café-rest"),
        ("pause‑2", "pause-2"),
        ("rest ‑ pause", "rest ‑ pause"),
        ("rest‐ pause", "rest‐ pause"),
        ("rest ‐pause", "rest ‐pause"),
        ("rest_‑pause", "rest_‑pause"),
        ("rest—pause", "rest—pause"),
        ("rest–pause", "rest–pause"),
        ("rest - pause", "rest - pause"),
    ],
)
def test_only_intraword_requested_hyphens_change(text: str, expected: str) -> None:
    original = draft("Quiet routines", paragraph=text)
    original["items"][0]["question"] = text
    result, changes = normalize_clean_draft(original, [])
    assert result["items"][0]["question"] == expected
    assert result["items"][0]["paragraphs"] == [expected]
    assert len(changes) == (0 if expected == text else 2)


def test_normalization_is_idempotent() -> None:
    once, changes = normalize_clean_draft(
        draft("nhs sleep‑friendly ROUTINES."), ["NHS"]
    )
    twice, later_changes = normalize_clean_draft(once, ["NHS"])
    assert changes
    assert twice == once
    assert later_changes == []


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"items": "invalid"},
        {"items": ["invalid"]},
        {"items": [{"title": 3, "question": None, "paragraphs": [False]}]},
        {"items": [{"title": "Rest", "paragraphs": "one paragraph"}]},
    ],
)
def test_invalid_structure_is_left_for_schema_validation(value: dict[str, Any]) -> None:
    result, changes = normalize_clean_draft(value, [])
    assert result == value
    assert result is not value
    assert changes == []


def test_no_structure_or_extra_field_repair() -> None:
    original = draft("Quiet routines")
    original["unrelated"] = "sleep‑friendly"
    original["items"][0]["extra"] = "sleep‑friendly"
    result, changes = normalize_clean_draft(original, [])
    assert result["unrelated"] == result["items"][0]["extra"] == "sleep‑friendly"
    assert len(result["items"]) == 1
    assert len(result["items"][0]["paragraphs"]) == 1
    assert changes == []


def test_allowlist_preserves_first_canonical_entry_and_unicode_matching() -> None:
    normalized, _ = normalize_clean_draft(
        draft("uk routines for ırs."), ["UK", "uk", "IRS"]
    )
    assert normalized["items"][0]["title"] == "UK routines for IRS"

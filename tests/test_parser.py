"""Parser boundaries and Q&A wrapping without network calls."""

import pytest

from editorial_qa_evals.models import Entry
from editorial_qa_evals.parser import parse_body, parse_items, parse_qa, quote_state


def test_numbered_items_and_labels() -> None:
    items = parse_items(
        "Intro.\n**1. Quiet pause**\nUnlabelled intro.\n"
        "**Why it matters:** Rest helps.\nWrapped prose.\n"
        "**How to do it**: Allow time.\n\nDetached closer.\n\n"
        "2) Evening rhythm\n**Why it matters:** Familiar patterns help."
    )
    assert [item.number for item in items] == [1, 2]
    assert items[0].title == "Quiet pause"
    assert items[0].intro == ("Unlabelled intro.",)
    assert items[0].orphans == ("Detached closer.",)
    assert items[0].sections[0].text == "Rest helps.\nWrapped prose."
    assert items[0].sections[1].label == "How to do it"
    assert items[1].intro == items[1].orphans == ()
    assert parse_items("No numbered items.") == ()


@pytest.mark.parametrize(
    "text,state",
    [
        ('"Rest helps."', "quoted"),
        ("‘Rest helps.’", "quoted"),
        ("'Rest helps.'", "quoted"),
        ("“Rest helps.”", "quoted"),
        ("Rest helps.", "unquoted"),
        ("Rest helps.”", "partial"),
        ("“Rest helps.", "partial"),
        ('"', "partial"),
        ("", "unquoted"),
    ],
)
def test_quote_states(text: str, state: str) -> None:
    assert quote_state(text) == state


def test_qa_body_formats_and_field_priority() -> None:
    pairs = parse_qa("1. What helps?\nRest helps.\n2. What else?\nA: Quiet helps.")
    assert [pair.question for pair in pairs] == ["What helps?", "What else?"]
    assert [pair.answer for pair in pairs] == ["Rest helps.", "Quiet helps."]
    pairs = parse_qa(
        "Q: What helps?\nA: Rest helps.\nQuestion 2: What else?\nAnswer 2: Quiet helps."
    )
    assert len(pairs) == 2
    assert pairs[1].answer == "Quiet helps."
    assert parse_qa("Q: What helps?")[0].answer is None
    pairs = parse_qa("Ignored body", ["What helps?"], ["Rest.", "Quiet."])
    assert pairs[1].question is None
    assert parse_qa("Unstructured prose.") == ()


def test_preamble_is_preserved() -> None:
    entry = Entry(
        id="syn-0001",
        source="synthetic",
        piece_type="simple_pitch_list",
        region="UK",
        task_name="Rest",
        brief={
            "tips": [],
            "hook": "Rest",
            "tone": "Precise",
            "expert": {"credential": "Reviewer", "specialism": "Rest"},
        },
        approved_labels=[],
        body="Framing.\n1. Quiet pause\nUnlabelled prose.",
    )
    parsed = parse_body(entry)
    assert parsed.preamble == "Framing."
    assert parsed.items[0].intro == ("Unlabelled prose.",)


def test_explicit_numbers_and_orphan_answers() -> None:
    pairs = parse_qa(
        "A1: An orphan answer.\nQ2: What helps?\nA2: Rest.\nA3: Another orphan."
    )
    assert [(p.number, p.question, p.answer) for p in pairs] == [
        (1, None, "An orphan answer."),
        (2, "What helps?", "Rest."),
        (3, None, "Another orphan."),
    ]
    pairs = parse_qa("Q2: What helps?\nA3: Rest.")
    assert pairs[0].number == 2 and pairs[0].answer is None
    assert pairs[1].number == 3 and pairs[1].question is None
    pairs = parse_qa("Q: What helps?\nA:\nQ: What else?\nQuiet.")
    assert pairs[0].answer is None
    assert pairs[1].answer == "Quiet."
    pairs = parse_qa("Q1: What helps?\nRest.\nA: Extra answer.")
    assert pairs[0].answer == "Rest."
    assert pairs[1].question is None


def test_windows_newline_orphan_boundary() -> None:
    items = parse_items(
        "1. Quiet pause\r\n**Why it matters:** Rest helps.\r\n\r\nDetached closer."
    )
    assert items[0].orphans == ("Detached closer.",)

"""Each fictional recipe changes a clean entry without invoking a model."""

import random

import httpx
import pytest

from editorial_qa_evals.deterministic import run_checks
from editorial_qa_evals.faults import RECIPES, apply_fault, available_recipes
from editorial_qa_evals.models import Entry
from editorial_qa_evals.parser import parse_items, parse_qa


def clean_entry(piece_type: str = "simple_pitch_list", region: str = "UK") -> Entry:
    tips = [f"Quiet pause {index}" for index in range(1, 6)]
    labels = ["Why it's not worth it", "What to buy instead", "Savings"]
    questions = [f"What helps with quiet pause {index}?" for index in range(1, 6)]
    answers = [
        f"A quiet pause helps with routine {index}. Familiar patterns support rest."
        for index in range(1, 6)
    ]
    if piece_type == "qa":
        body = "\n\n".join(
            f"Q{index}: {question}\nA{index}: {answer}"
            for index, (question, answer) in enumerate(
                zip(questions, answers, strict=True), 1
            )
        )
    else:
        parts = []
        for index in range(1, 6):
            if piece_type == "simple_pitch_list":
                content = "\n".join(
                    f"**{label}:** A quiet pause supports rest. Familiar patterns help."
                    for label in labels
                )
            else:
                content = (
                    "A quiet pause supports rest. Familiar patterns help.\n"
                    "**Top tip:** Allow room for a pause. Familiar patterns help."
                )
            parts.append(f"{index}. Quiet pause {index}\n{content}")
        body = "\n\n".join(parts)
        if piece_type == "cpr":
            body = (
                "The fictional medical reviewer studies quiet pauses.\n\n"
                "“Familiar patterns help.”\n\n" + body
            )
    return Entry.model_validate(
        {
            "id": "syn-0001",
            "source": "synthetic",
            "piece_type": piece_type,
            "region": region,
            "task_name": "Medical reviewer reveals 5 tips for rest",
            "brief": {
                "tips": tips,
                "hook": "Rest routines",
                "tone": "Precise",
                "expert": {
                    "credential": "Medical reviewer",
                    "specialism": "Rest routines",
                },
            },
            "approved_labels": labels if piece_type == "simple_pitch_list" else [],
            "body": body,
            "questions": questions if piece_type == "qa" else [],
            "answers": answers if piece_type == "qa" else [],
        }
    )


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_request(*args: object, **kwargs: object) -> None:
        raise AssertionError("Recipe tests must never invoke a model")

    monkeypatch.setattr(httpx.Client, "send", no_request)


@pytest.mark.parametrize("piece_type", ["simple_pitch_list", "qa", "cpr"])
def test_clean_fixture_and_metadata(piece_type: str) -> None:
    entry = clean_entry(piece_type)
    assert not [result for result in run_checks(entry) if result.result == "fail"]
    names = available_recipes(entry)
    assert names == sorted(set(names))
    assert all(name in RECIPES for name in names)
    assert {RECIPES[name].intended_verdict for name in names} >= {"REVISE", "MAJOR"}
    for recipe in RECIPES.values():
        assert set(recipe.checks) <= set(recipe.rubric_checks)


@pytest.mark.parametrize("name", RECIPES)
def test_each_recipe_targets_detectable_check_or_semantic_change(name: str) -> None:
    piece_type = "qa" if name in {"mixed_quotes", "bundled_q5"} else "simple_pitch_list"
    entry = clean_entry(piece_type)
    before = entry.model_dump()
    changed = apply_fault(entry, name, random.Random(7))
    assert entry.model_dump() == before
    assert changed.model_dump() != before
    assert changed.id == entry.id
    assert changed.brief == entry.brief
    assert changed.injected_faults is None
    assert changed.human is None
    failed = {
        result.check_id for result in run_checks(changed) if result.result == "fail"
    }
    assert set(RECIPES[name].checks) <= failed
    assert apply_fault(entry, name, random.Random(7)) == changed
    if piece_type == "qa":
        pairs = parse_qa(changed.body)
        assert [pair.question for pair in pairs] == changed.questions
        assert [pair.answer for pair in pairs] == changed.answers
        assert changed.questions[0] == entry.questions[0]
    assert len(changed.questions) == len(changed.answers)


@pytest.mark.parametrize("piece_type", ["simple_pitch_list", "qa", "cpr"])
@pytest.mark.parametrize(
    "name",
    ["count_plus", "count_minus", "dropped_tip", "em_dash", "region_swap", "filler"],
)
def test_shared_recipes_across_shapes(piece_type: str, name: str) -> None:
    entry = clean_entry(piece_type)
    changed = apply_fault(entry, name, random.Random(3))
    failed = {
        result.check_id for result in run_checks(changed) if result.result == "fail"
    }
    assert set(RECIPES[name].checks) <= failed
    count = (
        len(changed.questions) if piece_type == "qa" else len(parse_items(changed.body))
    )
    assert count == {"count_plus": 6, "count_minus": 4}.get(name, 5)
    if piece_type == "cpr":
        assert changed.body.startswith("The fictional medical reviewer")
    if name == "dropped_tip":
        if piece_type == "qa":
            assert changed.questions[-1] == changed.questions[0]
            assert changed.answers[-1] == changed.answers[0]
        else:
            items = parse_items(changed.body)
            assert items[-1].title == items[0].title


def test_qa_wrapping_and_region_direction() -> None:
    entry = clean_entry("qa", "US")
    quoted = entry.model_copy(
        update={"answers": [f"“{answer}”" for answer in entry.answers]}
    )
    changed = apply_fault(quoted, "em_dash", random.Random(1))
    assert changed.answers[0].startswith("“") and changed.answers[0].endswith("”")
    assert {result.check_id: result.result for result in run_checks(changed)}[
        "C6"
    ] == "pass"
    changed = apply_fault(quoted, "mixed_quotes", random.Random(1))
    assert {result.check_id: result.result for result in run_checks(changed)}[
        "C6"
    ] == "fail"
    changed = apply_fault(entry, "region_swap", random.Random(1))
    assert "colour" in changed.body
    assert {result.check_id: result.result for result in run_checks(changed)}[
        "C9"
    ] == "fail"


def test_semantic_mutations_are_explicit() -> None:
    entry = clean_entry()
    assert "5 mistakes" in apply_fault(entry, "noun_drift", random.Random(1)).task_name
    mistakes = entry.model_copy(
        update={"task_name": "Medical reviewer reveals 5 mistakes"}
    )
    assert "5 tips" in apply_fault(mistakes, "noun_drift", random.Random(1)).task_name
    assert apply_fault(
        entry, "generic_credential", random.Random(1)
    ).task_name.startswith("Expert reveals")
    changed = apply_fault(clean_entry("qa"), "bundled_q5", random.Random(1))
    assert changed.brief.tips[3] in changed.questions[4]
    assert changed.brief.tips[4] in changed.questions[4]
    assert " and " in changed.questions[4]
    assert (
        "scary" in apply_fault(entry, "clinical_colloquialism", random.Random(1)).body
    )


def test_applicability_and_rejections() -> None:
    entry = clean_entry("qa")
    assert "mini_labels" not in available_recipes(entry)
    assert "cost_placeholder" not in available_recipes(entry)
    broken = entry.model_copy(update={"answers": []})
    assert available_recipes(broken) == []
    no_items = clean_entry().model_copy(update={"body": "Unnumbered prose."})
    assert available_recipes(no_items) == []
    with pytest.raises(ValueError, match="Unknown fault"):
        apply_fault(entry, "not_a_recipe", random.Random(0))
    with pytest.raises(ValueError, match="does not apply"):
        apply_fault(entry, "cost_placeholder", random.Random(0))
    expert = entry.model_copy(
        update={
            "brief": entry.brief.model_copy(
                update={
                    "expert": entry.brief.expert.model_copy(
                        update={"credential": "Reviewer"}
                    )
                }
            ),
        }
    )
    assert "clinical_colloquialism" not in available_recipes(expert)
    assert "generic_credential" not in available_recipes(expert)


def test_compatible_combinations_keep_earlier_deterministic_faults() -> None:
    for piece_type in ["simple_pitch_list", "qa", "cpr"]:
        entry = clean_entry(piece_type)
        expected = set()
        for name in ["em_dash", "region_swap", "filler"]:
            entry = apply_fault(entry, name, random.Random(0))
            expected.update(RECIPES[name].checks)
        failed = {
            result.check_id for result in run_checks(entry) if result.result == "fail"
        }
        assert expected <= failed

"""Fictional clean entries and a separate body variant for every fault family."""

import copy
import json
from pathlib import Path

import pytest

from editorial_qa_evals.deterministic import (
    check_c9,
    check_j2,
    load_rules,
    run_checks,
)
from editorial_qa_evals.models import Entry
from editorial_qa_evals.parser import parse_body

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/deterministic.json").read_text()
)
RULES = load_rules()


def entry_for(name: str = "pitch", **changes: object) -> Entry:
    return Entry.model_validate({**copy.deepcopy(FIXTURES["clean"][name]), **changes})


@pytest.mark.parametrize("name", FIXTURES["clean"])
def test_clean_entries(name: str) -> None:
    results = {r.check_id: r for r in run_checks(entry_for(name), RULES)}
    expected_na = {
        "pitch": {"C3", "C6"},
        "cost": {"C6"},
        "qa": {"C1", "C2", "C3", "C12", "J2"},
        "cpr": {"C1", "C3", "C6", "C12"},
    }[name]
    assert len(results) == 10
    for check_id, result in results.items():
        assert result.result == ("na" if check_id in expected_na else "pass")
        assert result.evidence == []
        assert result.severity is None


@pytest.mark.parametrize("case", FIXTURES["faults"], ids=lambda case: case["name"])
def test_fault_bodies(case: dict) -> None:
    entry = entry_for(case["base"], **case["changes"])
    results = {r.check_id: r for r in run_checks(entry, RULES)}
    assert {key for key, result in results.items() if result.result == "fail"} == set(
        case["expected"]
    )
    for check_id, expected in case["expected"].items():
        result = results[check_id]
        assert result.severity == expected["severity"]
        assert any(
            expected["span"] in evidence.span
            and expected["item_number"] == evidence.item_number
            for evidence in result.evidence
        )
        assert set(result.model_dump()) == {
            "check_id",
            "result",
            "severity",
            "evidence",
        }


def test_no_count_promise_is_na() -> None:
    entry = entry_for(
        "cpr",
        task_name="Rest habits",
        brief={
            **FIXTURES["clean"]["cpr"]["brief"],
            "tips": [],
        },
    )
    assert {r.check_id: r.result for r in run_checks(entry, RULES)}["C11"] == "na"


@pytest.mark.parametrize(
    "title", ["A 2026 guide to rest", "50 years of rest", "Rest after 5 days"]
)
def test_non_count_numerals(title: str) -> None:
    entry = entry_for(task_name=title)
    assert {r.check_id: r.result for r in run_checks(entry, RULES)}["C11"] == "pass"


def test_empty_bodies_do_not_pass_structure() -> None:
    results = {r.check_id: r for r in run_checks(entry_for(body=""), RULES)}
    assert results["C1"].result == "fail"
    assert results["C11"].result == "fail"
    qa = {r.check_id: r for r in run_checks(entry_for("qa", body=""), RULES)}
    assert qa["C6"].result == "fail"


def test_region_direction_boundaries_and_distinct_families() -> None:
    entry = entry_for(region="US", body="A colour for Mum on holiday.")
    assert check_c9(entry, parse_body(entry), RULES["swaps"]).severity == "MAJOR"
    entry = entry_for(body="color color color. Colorful harmonica.")
    result = check_c9(entry, parse_body(entry), RULES["swaps"])
    assert result.severity == "FORMAT"
    assert [e.span for e in result.evidence] == ["color", "color", "color"]


@pytest.mark.parametrize(
    "token",
    ["$", "401(k)", "IRS", "Medicare", "Mom", "yard", "vacation", "apartment", "color"],
)
def test_each_region_swap(token: str) -> None:
    entry = entry_for(body=token)
    result = check_c9(entry, parse_body(entry), RULES["swaps"])
    assert result.result == "fail"
    assert result.evidence[0].span == token


def test_allowlist_and_heading_cases() -> None:
    entry = entry_for(body="1. Rest near Lumenvale\n**Why it matters:** Rest helps.")
    parsed = parse_body(entry)
    assert check_j2(entry, parsed, []).result == "fail"
    assert check_j2(entry, parsed, ["Lumenvale"]).result == "pass"
    acronym = entry_for(body="1. NHS rest habits\n**Why it matters:** Rest helps.")
    assert (
        check_j2(acronym, parse_body(acronym), RULES["proper_nouns"]).result == "pass"
    )


def test_structured_qa_text_is_scanned() -> None:
    entry = entry_for(
        "qa", body="", questions=["What helps?"], answers=["In conclusion, color—rest."]
    )
    results = {r.check_id: r for r in run_checks(entry, RULES)}
    assert results["C6"].result == "pass"
    for check in ["C8", "C9", "J4"]:
        assert results[check].result == "fail"
        assert results[check].evidence[0].item_number == 1
        assert results[check].evidence[0].location == "answer"


def test_accented_latin_and_word_boundaries() -> None:
    entry = entry_for(
        body="Rest at the café. Recolouring is colourful. In conclusions."
    )
    results = {r.check_id: r for r in run_checks(entry, RULES)}
    assert all(results[check].result == "pass" for check in ["C8", "C9", "J4"])


def test_all_approved_headers_and_top_tip_exception() -> None:
    body = FIXTURES["clean"]["pitch"]["body"].replace(
        "**How to do it:**", "**How to do it**:"
    )
    results = {r.check_id: r for r in run_checks(entry_for(body=body), RULES)}
    assert results["C1"].result == results["C2"].result == "pass"
    entry = entry_for(
        approved_labels=["Top Tip"], body="1. Rest habits\n**Top Tip:** Rest helps."
    )
    assert {r.check_id: r for r in run_checks(entry, RULES)}["C2"].result == "pass"


def test_numbered_qa_evidence_and_extra_answer_count() -> None:
    entry = entry_for(
        "qa", body="Q1: What helps?\nA1: Quiet.\nQ2: What else?\nA2: Color—rest."
    )
    results = {r.check_id: r for r in run_checks(entry, RULES)}
    assert results["C8"].evidence[0].item_number == 2
    assert results["C9"].evidence[0].item_number == 2
    entry = entry_for(
        "qa", body=FIXTURES["clean"]["qa"]["body"] + "\nA3: A ghost answer."
    )
    results = {r.check_id: r for r in run_checks(entry, RULES)}
    assert results["C6"].result == "fail"
    assert results["C6"].evidence[0].item_number == 3
    assert results["C11"].result == "pass"


def test_repeated_checks_are_pure_and_rules_are_injectable() -> None:
    entry = entry_for()
    before = entry.model_dump()
    rules = copy.deepcopy(RULES)
    rules["offenders"] = []
    assert run_checks(entry, rules) == run_checks(entry, rules)
    assert entry.model_dump() == before
    assert rules["offenders"] == []


def test_numbered_titles_without_sections_and_non_list_j2() -> None:
    entry = entry_for(body="1. Rest habits")
    results = {r.check_id: r for r in run_checks(entry, RULES)}
    assert results["C1"].result == "fail"
    assert results["C2"].result == "pass"
    assert results["J2"].result == "pass"
    entry = entry_for("cpr", body="Plain prose.")
    assert {r.check_id: r for r in run_checks(entry, RULES)}["J2"].result == "na"


def test_optional_rule_directory() -> None:
    assert load_rules(Path(__file__).resolve().parents[1] / "rules") == RULES


def test_global_text_is_not_a_second_affected_item() -> None:
    body = "A framing sentence.\n" + FIXTURES["clean"]["pitch"]["body"].replace(
        "1. Late bedtime", "1. Late bedtime\nAn item intro.", 1
    )
    results = {r.check_id: r for r in run_checks(entry_for(body=body), RULES)}
    assert results["C12"].severity == "FLAG"


def test_mixed_script_evidence_is_a_literal_span() -> None:
    text = "Latin残mixed留text"
    results = {r.check_id: r for r in run_checks(entry_for(body=text), RULES)}
    assert results["C8"].evidence[0].span == text


def test_mini_label_evidence_is_not_duplicated() -> None:
    body = FIXTURES["clean"]["pitch"]["body"].replace(
        "A steady rhythm", "**Example:** A steady rhythm", 1
    )
    results = {r.check_id: r for r in run_checks(entry_for(body=body), RULES)}
    assert len(results["C2"].evidence) == 1


@pytest.mark.parametrize(
    "region,text", [("UK", "$25"), ("UK", "USD 25"), ("US", "£25"), ("US", "GBP 25")]
)
def test_currency_symbols_and_aliases(region: str, text: str) -> None:
    entry = entry_for(region=region, body=text)
    result = check_c9(entry, parse_body(entry), RULES["swaps"])
    assert result.result == "fail"
    assert result.severity == "FORMAT"
    assert result.evidence[0].span in text


def test_currency_aliases_count_as_one_family() -> None:
    entry = entry_for(body="USD 25 and $25 with color.")
    result = check_c9(entry, parse_body(entry), RULES["swaps"])
    assert result.severity == "FORMAT"
    assert len(result.evidence) == 3


def test_uniformly_quoted_qa_passes() -> None:
    body = (
        FIXTURES["clean"]["qa"]["body"]
        .replace("A steady routine helps.", "“A steady routine helps.”")
        .replace("A quiet pause helps.", "“A quiet pause helps.”")
    )
    entry = entry_for("qa", body=body)
    assert {r.check_id: r for r in run_checks(entry, RULES)}["C6"].result == "pass"

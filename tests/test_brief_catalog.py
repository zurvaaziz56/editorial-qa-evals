"""Catalog safety, representative planning and run-level diversity invariants."""

import copy
import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from editorial_qa_evals.brief_catalog import (
    BANNED,
    CATEGORIES,
    CLINICAL_DOMAINS,
    check_diversity,
    draw_count,
    headline,
    load_catalog,
)
from editorial_qa_evals.deterministic import load_rules, run_checks
from editorial_qa_evals.diversity import app, diversity_report
from editorial_qa_evals.faults import apply_fault, available_recipes
from editorial_qa_evals.generation_errors import GenerationError
from editorial_qa_evals.models import Entry
from editorial_qa_evals.synthetic import (
    Draft,
    DraftValidationError,
    draft_schema,
    generate_dataset,
    plan_entries,
    render_draft,
    resample_entry,
    statistic_context,
)


def test_catalog_covers_required_domains_and_categories() -> None:
    catalog = load_catalog()
    assert set(catalog.domains) == {
        "personal_finance",
        "mortgages_property",
        "travel",
        "home_garden",
        "sleep_health",
        "dental",
        "pets",
        "careers",
        "parenting",
        "cybersecurity",
        "motoring",
        "food_nutrition",
    }
    assert len(catalog.headline_templates) >= 6
    assert len({c.name for d in catalog.domains.values() for c in d.credentials}) >= 36
    for domain in catalog.domains.values():
        assert len(domain.credentials) >= 3
        assert len(set(domain.hooks)) >= 3
        assert set(domain.tips) == set(CATEGORIES)
        assert all(len(set(candidates)) >= 8 for candidates in domain.tips.values())


@pytest.mark.parametrize(
    "fault",
    [
        "short_tips",
        "missing_category",
        "duplicate_tip",
        "duplicate_credential",
        "clinical_voice",
        "clinical_name",
        "banned_hook",
        "banned_subject",
        "banned_tip",
        "banned_organisation",
        "bad_template",
        "no_credential",
        "bad_weights",
        "short_domains",
        "short_templates",
        "bad_structure",
    ],
)
def test_catalog_rejects_invalid_config_before_generation(
    tmp_path: Path, fault: str
) -> None:
    data = load_catalog().model_dump()
    domain = data["domains"]["personal_finance"]
    if fault == "short_tips":
        domain["tips"]["mistakes"] = domain["tips"]["mistakes"][:7]
    elif fault == "missing_category":
        del domain["tips"]["habits"]
    elif fault == "duplicate_tip":
        domain["tips"]["habits"][0] = domain["tips"]["mistakes"][0]
    elif fault == "duplicate_credential":
        domain["credentials"][1] = domain["credentials"][0]
    elif fault == "clinical_voice":
        domain["credentials"][0]["voice_tier"] = "clinical"
    elif fault == "clinical_name":
        domain["credentials"][0]["name"] = "Dentist"
    elif fault.startswith("banned_"):
        key = fault.removeprefix("banned_")
        if key == "hook":
            domain["hooks"][0] = "An INVENTED budget"
        elif key == "tip":
            domain["tips"]["tips"][0] = "Fictional budgeting"
        else:
            domain["stat_organisation" if key == "organisation" else key] = "simulation"
    elif fault == "bad_template":
        data["headline_templates"]["reveals"] = "{unknown}"
    elif fault == "no_credential":
        data["headline_templates"]["reveals"] = "Expert reveals {count} {category}"
    elif fault == "bad_weights":
        data["count_weights"] = [0.5, 0.25, 0.25]
    elif fault == "short_domains":
        del data["domains"]["travel"]
    elif fault == "short_templates":
        data["headline_templates"] = {"reveals": data["headline_templates"]["reveals"]}
    else:
        data["version"] = "unsupported"
    path = tmp_path / "catalog.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(GenerationError):
        load_catalog(path)


def test_count_draws_use_the_documented_weights() -> None:
    catalog = load_catalog()
    actual_rng, expected_rng = random.Random(12), random.Random(12)
    assert [draw_count(catalog, actual_rng) for _ in range(100)] == [
        expected_rng.choices([3, 5, 7], weights=[0.25, 0.5, 0.25], k=1)[0]
        for _ in range(100)
    ]
    rng = random.Random(7)
    counts = Counter(draw_count(catalog, rng) for _ in range(20000))
    for value, weight in zip(catalog.count_values, catalog.count_weights, strict=True):
        assert abs(counts[value] / 20000 - weight) < 0.015


@pytest.mark.parametrize("n", [20, 21, 40, 80, 100])
@pytest.mark.parametrize("seed", [0, 7, 42, 173])
def test_diversity_and_clinical_gating_hold_for_seeded_plans(n: int, seed: int) -> None:
    plans = plan_entries(n, seed)
    entries = [p.entry for p in plans]
    assert not check_diversity(entries)
    catalog = load_catalog()
    for entry in entries:
        brief = entry.brief
        assert len(brief.tips) in {3, 5, 7}
        assert str(len(brief.tips)) in entry.task_name
        assert brief.noun_category in entry.task_name
        assert brief.expert.credential.lower() in entry.task_name.lower()
        assert not BANNED.search(entry.task_name + brief.hook)
        assert not entry.task_name.startswith("Expert")
        if brief.voice_tier == "clinical":
            assert brief.domain in CLINICAL_DOMAINS
        assert (
            brief.tone
            == {
                "clinical": "Clinical and precise",
                "accessible_precise": "Accessible and precise",
                "lifestyle": "Warm and practical",
            }[brief.voice_tier]
        )
        assert brief.expert.credential in {
            c.name for c in catalog.domains[brief.domain].credentials
        }
    if n == 80:
        assert len({e.brief.domain for e in entries}) == 12
        assert len({e.brief.headline_template for e in entries}) == 8


def test_all_headline_templates_keep_specific_credentials_and_noun_contract() -> None:
    catalog = load_catalog()
    domain = catalog.domains["dental"]
    credential = domain.credentials[0]
    for template in catalog.headline_templates:
        for category in CATEGORIES:
            title = headline(catalog, template, domain, credential, 7, category)
            assert category in title and "7" in title
            assert "dentist" in title.lower()
            assert not BANNED.search(title)


def test_impossible_unique_tip_budget_is_rejected_before_calls(tmp_path: Path) -> None:
    def forbidden(*args: Any) -> dict[str, Any]:
        pytest.fail("Catalog capacity must be checked before model calls")

    with pytest.raises(GenerationError, match="capacity exhausted"):
        generate_dataset(1000, 7, tmp_path / "data.jsonl", tmp_path / "run", forbidden)
    assert not (tmp_path / "run").exists()


def test_recovery_retains_diversity_and_tip_ownership() -> None:
    entries = [p.entry for p in plan_entries(80, 7)]
    for attempt in range(1, 4):
        changed = [resample_entry(e, 7, attempt) for e in entries]
        assert not check_diversity(changed)
        for before, after in zip(entries, changed, strict=True):
            assert set(before.brief.tips) == set(after.brief.tips)
            assert before.brief.tips != after.brief.tips
            assert before.task_name == after.task_name
            assert before.brief.voice_tier == after.brief.voice_tier
            assert before.brief.hook != after.brief.hook


def draft_for(entry: Entry) -> Draft:
    return Draft.model_validate(
        {
            "items": [
                {
                    "title": tip,
                    "question": f"What matters about {tip.lower()}?",
                    "paragraphs": [
                        "This specific action deserves attention. "
                        "A careful review is useful."
                    ]
                    * (
                        len(entry.approved_labels)
                        if entry.piece_type == "simple_pitch_list"
                        else 1
                        if entry.piece_type == "qa"
                        else 2
                    ),
                    "statistic": {
                        "claim": "leaving engines idling while clearing the windscreen",
                        "relevant": True,
                        "rationale": "Measures the idling behaviour directly",
                    }
                    if entry.piece_type == "cpr"
                    else None,
                }
                for tip in entry.brief.tips
            ]
        }
    )


@pytest.mark.parametrize("word", ["fictional", "INVENTED", "Simulation"])
@pytest.mark.parametrize("field", ["title", "question", "paragraph", "statistic"])
def test_banned_words_reject_model_output(word: str, field: str) -> None:
    entry = next(p.entry for p in plan_entries(20, 7) if p.entry.piece_type == "cpr")
    draft = draft_for(entry)
    item = draft.items[0]
    if field == "paragraph":
        item.paragraphs[0] = f"A {word} action needs attention. Review the details."
    elif field == "statistic":
        item.statistic.claim = f"using a {word} approach"
    else:
        setattr(item, field, f"A {word} action" + ("?" if field == "question" else ""))
    with pytest.raises(DraftValidationError):
        render_draft(entry, draft)


@pytest.mark.parametrize("count", [3, 5, 7])
def test_dynamic_schema_and_renderer_enforce_entry_count(count: int) -> None:
    entry = next(
        p.entry for p in plan_entries(80, 7) if len(p.entry.brief.tips) == count
    )
    schema = draft_schema(2, count)
    assert schema["properties"]["items"]["minItems"] == count
    assert schema["properties"]["items"]["maxItems"] == count
    draft = draft_for(entry)
    draft.items = draft.items[:-1]
    with pytest.raises(DraftValidationError, match="count must equal"):
        render_draft(entry, draft)


def test_cpr_stats_have_context_and_failed_relevance_checks_are_dropped() -> None:
    plan = next(p for p in plan_entries(80, 7) if p.entry.brief.domain == "motoring")
    entry = plan.entry.model_copy(update={"piece_type": "cpr", "approved_labels": []})
    draft = draft_for(entry)
    context = statistic_context(entry)
    assert context["region"] == entry.region and context["year"] == 2026
    assert context["synthetic_source"] is True
    draft.items[1].statistic.relevant = False
    draft.items[1].statistic.claim = "unrelated spending habits"
    rendered = render_draft(entry, draft)
    assert (
        rendered.body.count("https://source.invalid/survey/")
        == len(entry.brief.tips) - 1
    )
    assert "unrelated spending habits" not in rendered.body
    assert "leaving engines idling" in rendered.body
    assert context["organisation"] in rendered.body
    assert re.search(r"\d+% of (600|800|1200|1600|2000) " + entry.region, rendered.body)
    assert not BANNED.search(rendered.body)
    assert rendered == render_draft(entry, copy.deepcopy(draft))
    assert not [r for r in run_checks(rendered) if r.result == "fail"]
    draft.items[0].statistic = None
    with pytest.raises(DraftValidationError, match="relevance self-check"):
        render_draft(entry, draft)


def test_mocked_model_receives_voice_tier_counts_and_statistic_selfcheck(
    tmp_path: Path,
) -> None:
    seen = []

    def completion(system: str, user: str, seed: int) -> dict[str, Any]:
        payload = json.JSONDecoder().raw_decode(user)[0]
        assert payload["voice_tier"] == payload["brief"]["voice_tier"]
        assert "self-check EVERY" in system
        assert "ordinary" in system and "proportionate" in system
        assert payload["response_schema"]["properties"]["items"]["maxItems"] == len(
            payload["brief"]["tips"]
        )
        # A mocked response exercises the full schema, validation and publication path.
        entry = Entry.model_validate(
            {
                **{k: v for k, v in payload.items() if k in Entry.model_fields},
                "body": "",
            }
        )
        draft = draft_for(entry)
        if entry.piece_type == "cpr":
            assert payload["statistic_context"]["region"] == entry.region
            # A deliberately unrelated claim must be excluded by the relevance gate.
            for item in draft.items:
                item.statistic.relevant = False
        else:
            assert payload["statistic_context"] is None
        seen.append(entry)
        return {"choices": [{"message": {"content": draft.model_dump_json()}}]}

    out = tmp_path / "public/synthetic.jsonl"
    setattr(completion, "max_tokens", 1024)
    summary = generate_dataset(80, 7, out, tmp_path / "run", completion)
    assert len(seen) == summary["entries"] == 80
    assert summary["cpr_statistics"]["rendered"] == 0
    assert summary["cpr_statistics"]["dropped"] > 0
    public = [Entry.model_validate_json(line) for line in out.read_text().splitlines()]
    assert not check_diversity(public)
    assert not BANNED.search(" ".join(e.body for e in public))
    report = CliRunner().invoke(app, [str(out)])
    assert report.exit_code == 0, report.output
    assert "Diversity checks: PASS" in report.output
    assert "Top 25 content words" in report.output
    for title in ("Domains", "Credentials", "Headline templates", "Counts"):
        assert f"### {title}" in report.output

    def forbidden(system: str, user: str, seed: int) -> dict[str, Any]:
        pytest.fail("Replay must not call the API")

    replay_out = tmp_path / "replayed/synthetic.jsonl"
    replayed = generate_dataset(
        80,
        7,
        replay_out,
        tmp_path / "replayed-run",
        forbidden,
        replay_run=tmp_path / "run",
    )
    assert replayed == summary
    assert replay_out.read_bytes() == out.read_bytes()
    saved = json.loads((tmp_path / "run/config.json").read_text())
    assert saved["max_tokens"] == 1024


def test_diversity_report_rejects_bad_distributions_and_duplicate_tips(
    tmp_path: Path,
) -> None:
    entries = [p.entry for p in plan_entries(20, 7)]
    assert "Diversity checks: PASS" in diversity_report(entries)
    entry = entries[0]
    duplicate = [entry] * 20
    assert len(check_diversity(duplicate)) == 4
    path = tmp_path / "bad.jsonl"
    path.write_text("\n".join(e.model_dump_json() for e in duplicate))
    assert CliRunner().invoke(app, [str(path)]).exit_code == 1
    assert check_diversity(entries[:1])  # Actual survivors, not requested n.


def test_specific_headlines_are_generic_only_after_injection() -> None:
    entries = [p.entry for p in plan_entries(80, 7)]
    eligible = []
    for entry in entries:
        clean = render_draft(entry, draft_for(entry))
        if "generic_credential" in available_recipes(clean):
            eligible.append(clean)
    assert eligible
    changed = apply_fault(eligible[0], "generic_credential", random.Random(7))
    assert changed.task_name.startswith("Expert")


def test_nonmedical_red_flags_never_receive_medical_labels() -> None:
    entries = [p.entry for p in plan_entries(100, 7)]
    for entry in entries:
        if (
            entry.piece_type == "simple_pitch_list"
            and entry.brief.noun_category == "red flags"
        ):
            assert any("professional" in label for label in entry.approved_labels) == (
                entry.brief.voice_tier == "clinical"
            )


def test_wastes_of_money_headline_count_is_not_ignored() -> None:
    entry = next(
        p.entry
        for p in plan_entries(80, 7)
        if p.entry.brief.noun_category == "wastes of money"
    )
    entry = render_draft(entry, draft_for(entry))
    # Break only the headline promise, retaining a body matching brief.tips.
    changed = entry.model_copy(
        update={"task_name": "Accountant reveals 9 wastes of money"}
    )
    result = next(r for r in run_checks(changed, load_rules()) if r.check_id == "C11")
    assert result.result == "fail"
    assert any(e.location == "task_name" for e in result.evidence)


def test_diversity_caps_use_exact_boundaries() -> None:
    entries = [p.entry.model_copy(deep=True) for p in plan_entries(20, 7)]
    for entry in entries[:3]:
        entry.brief.domain = "boundary-domain"
    for entry in entries[:2]:
        entry.brief.expert.credential = "Boundary credential"
    for entry in entries[:5]:
        entry.brief.headline_template = "boundary-template"
    assert not check_diversity(entries)
    for field, index, value, prefix in (
        ("domain", 3, "boundary-domain", "domain"),
        ("credential", 2, "Boundary credential", "credential"),
        ("headline_template", 5, "boundary-template", "headline_template"),
    ):
        changed = copy.deepcopy(entries)
        target = (
            changed[index].brief.expert
            if field == "credential"
            else changed[index].brief
        )
        setattr(target, field, value)
        assert any(issue.startswith(prefix) for issue in check_diversity(changed))

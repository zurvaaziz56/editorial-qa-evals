"""Mocked regressions for clean-only repair, feedback and batch recovery."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from editorial_qa_evals import synthetic
from editorial_qa_evals.deterministic import run_checks
from editorial_qa_evals.models import Entry


def payload(user: str) -> dict[str, Any]:
    return json.JSONDecoder().raw_decode(user)[0]


def response(user: str) -> dict[str, Any]:
    request = payload(user)
    items = [
        {
            "statistic": {
                "claim": "following a careful routine",
                "relevant": False,
                "rationale": "This generic claim does not support the specific tip",
            }
            if request["piece_type"] == "cpr"
            else None,
            "title": tip,
            "question": f"What supports {tip.lower()}?",
            "paragraphs": ["A familiar rhythm supports rest. Quiet pauses help."]
            * request["paragraphs_per_item"],
        }
        for tip in request["brief"]["tips"]
    ]
    return {"choices": [{"message": {"content": json.dumps({"items": items})}}]}


def edit(
    raw: dict[str, Any],
    *,
    title: str | None = None,
    paragraphs: list[str] | None = None,
) -> dict[str, Any]:
    value = json.loads(raw["choices"][0]["message"]["content"])
    if title is not None:
        value["items"][0]["title"] = title
    if paragraphs is not None:
        value["items"][0]["paragraphs"] = paragraphs
    raw["choices"][0]["message"]["content"] = json.dumps(value)
    return raw


def test_normalization_logged_but_injected_faults_survive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_inject = synthetic.inject_faults

    def completion(system: str, user: str, seed: int) -> dict[str, Any]:
        raw = response(user)
        native = "nhs" if payload(user)["region"] == "UK" else "irs"
        return edit(
            raw,
            title=f"quiet {native} routines.",
            paragraphs=["A well\u2011timed rhythm supports rest. Quiet pauses help."]
            * payload(user)["paragraphs_per_item"],
        )

    def inject(
        entry: Entry, verdict: str, rng: Any, rules: Any
    ) -> tuple[Entry, list[str]]:
        changed, names = original_inject(entry, verdict, rng, rules)
        changed = changed.model_copy(
            update={
                "body": changed.body.replace("1. ", "1. lowercase ", 1)
                + "\nAn injected\u2011hyphen remains."
            }
        )
        return changed, list(set(names) | {"em_dash"})

    monkeypatch.setattr(synthetic, "inject_faults", inject)
    out, run = tmp_path / "public/synthetic.jsonl", tmp_path / "run"
    synthetic.generate_dataset(20, 7, out, run, completion)
    entries = [Entry.model_validate_json(line) for line in out.read_text().splitlines()]
    pitch = next(entry for entry in entries if entry.piece_type == "simple_pitch_list")
    native = "NHS" if pitch.region == "UK" else "IRS"
    assert f"1. lowercase Quiet {native} routines" in pitch.body
    assert "well-timed" in pitch.body
    assert "injected\u2011hyphen" in pitch.body
    failures = {r.check_id for r in run_checks(pitch) if r.result == "fail"}
    assert {"C8", "J2"} <= failures
    attempts = [
        json.loads(path.read_text()) for path in (run / "attempts").glob("*.json")
    ]
    assert all(attempt["status"] == "passed" for attempt in attempts)
    assert all(attempt["normalizations"] for attempt in attempts)
    assert {
        change["operation"]
        for attempt in attempts
        for change in attempt["normalizations"]
    } == {"word_hyphen", "sentence_case", "title_punctuation"}


def test_feedback_has_exact_failed_check_spans(tmp_path: Path) -> None:
    prompts = []

    def completion(system: str, user: str, seed: int) -> dict[str, Any]:
        prompts.append(user)
        raw = response(user)
        if len(prompts) == 1:
            foreign = "color" if payload(user)["region"] == "UK" else "colour"
            return edit(
                raw,
                paragraphs=[f"A {foreign}—detail supports rest. Quiet pauses help."]
                * payload(user)["paragraphs_per_item"],
            )
        return raw

    summary = synthetic.generate_dataset(
        20, 7, tmp_path / "public/synthetic.jsonl", tmp_path / "run", completion
    )
    feedback = json.loads(
        prompts[1].split("Validation feedback from previous attempts:\n")[1]
    )
    failures = {item["check_id"]: item for item in feedback[0]["failures"]}
    assert set(failures) == {"C8", "C9"}
    assert failures["C8"]["evidence"][0]["span"] == "—"
    assert any(e["item_number"] == 1 for e in failures["C8"]["evidence"])
    assert summary["failure_summary"] == {"C8": 1, "C9": 1}


def test_paragraph_feedback_and_fifth_attempt(tmp_path: Path) -> None:
    counts: Counter[str] = Counter()
    prompts = []

    def completion(system: str, user: str, seed: int) -> dict[str, Any]:
        request = payload(user)
        counts[request["id"]] += 1
        if request["id"] == "syn-0001":
            prompts.append(user)
            if counts[request["id"]] < 5:
                return edit(
                    response(user),
                    paragraphs=["A rhythm supports rest. Quiet pauses help."],
                )
        return response(user)

    summary = synthetic.generate_dataset(
        20, 7, tmp_path / "public/synthetic.jsonl", tmp_path / "run", completion
    )
    assert counts["syn-0001"] == 5
    assert summary["resamples"] == 0
    assert summary["entries"] == 20
    feedback = json.loads(
        prompts[1].split("Validation feedback from previous attempts:\n")[1]
    )[0]["failures"][0]
    assert feedback["check_id"] == "PARAGRAPH_COUNT"
    assert feedback["actual"] == 1
    assert feedback["expected"] == payload(prompts[0])["paragraphs_per_item"]
    assert feedback["evidence"] == ["A rhythm supports rest. Quiet pauses help."]


def test_resample_keeps_id_region_and_type_and_is_logged(tmp_path: Path) -> None:
    prompts = []

    def completion(system: str, user: str, seed: int) -> dict[str, Any]:
        if payload(user)["id"] == "syn-0001":
            prompts.append(payload(user))
            if len(prompts) <= 5:
                return {"choices": []}
        return response(user)

    out, run = tmp_path / "public/synthetic.jsonl", tmp_path / "run"
    summary = synthetic.generate_dataset(20, 7, out, run, completion)
    assert summary["entries"] == 20 and summary["resamples"] == 1
    assert len(prompts) == 6
    for key in ("id", "region", "piece_type"):
        assert prompts[0][key] == prompts[5][key]
    assert prompts[0]["brief"] != prompts[5]["brief"]
    log = json.loads((run / "resamples/syn-0001-1.json").read_text())
    assert log["previous_brief"]["brief"] != log["new_brief"]["brief"]
    assert log["reason"][0]["check_id"] == "SCHEMA"


@pytest.mark.parametrize("failed_count", [1, 2, 3])
def test_ten_percent_threshold_and_continued_batch(
    tmp_path: Path, failed_count: int
) -> None:
    failed_ids = {f"syn-{i:04d}" for i in range(1, failed_count + 1)}
    counts: Counter[str] = Counter()

    def completion(system: str, user: str, seed: int) -> dict[str, Any]:
        id = payload(user)["id"]
        counts[id] += 1
        return {"choices": []} if id in failed_ids else response(user)

    out, run = tmp_path / "public/synthetic.jsonl", tmp_path / "run"
    if failed_count <= 2:
        summary = synthetic.generate_dataset(20, 7, out, run, completion)
        assert summary["entries"] == 20 - failed_count
        assert summary["failed_entries"] == failed_count
        assert set(summary["failed_ids"]) == failed_ids
        assert (
            len(out.with_name("smoke_ids.txt").read_text().splitlines())
            == 20 - failed_count
        )
        assert len(out.read_text().splitlines()) == 20 - failed_count
    else:
        with pytest.raises(
            synthetic.BatchGenerationError, match="more than 10%"
        ) as error:
            synthetic.generate_dataset(20, 7, out, run, completion)
        assert error.value.summary["failed_entries"] == failed_count
        assert not out.exists()
        assert not out.with_name("faults.jsonl").exists()
    assert len(counts) == 20  # Later IDs still run after earlier ones exhaust recovery.
    assert all(counts[id] == 20 for id in failed_ids)
    summary = json.loads((run / "validation.json").read_text())
    assert summary["failure_summary"] == {"SCHEMA": failed_count * 20}
    assert summary["resamples"] == failed_count * 3


def test_dynamic_schema_keeps_required_paragraph_count() -> None:
    for count in (1, 2, 3):
        schema = synthetic.draft_schema(count)
        array = schema["$defs"]["DraftItem"]["properties"]["paragraphs"]
        assert array["minItems"] == array["maxItems"] == count
        assert schema["properties"]["items"]["minItems"] == 5


def test_partial_resampled_run_replays_without_model_calls(tmp_path: Path) -> None:
    counts: Counter[str] = Counter()

    def completion(system: str, user: str, seed: int) -> dict[str, Any]:
        id = payload(user)["id"]
        counts[id] += 1
        if id == "syn-0001":
            raise synthetic.GenerationError("Generation API returned HTTP 503")
        if id == "syn-0002" and counts[id] <= 5:
            return {"choices": []}
        return response(user)

    out, run = tmp_path / "public/synthetic.jsonl", tmp_path / "run"
    summary = synthetic.generate_dataset(20, 7, out, run, completion, max_rpm=7)
    assert summary["failed_ids"] == ["syn-0001"]
    assert summary["resamples"] == 4

    def forbidden(system: str, user: str, seed: int) -> dict[str, Any]:
        pytest.fail("Offline replay must not call the API")

    replay_out = tmp_path / "replay/synthetic.jsonl"
    replayed = synthetic.generate_dataset(
        20,
        7,
        replay_out,
        tmp_path / "replay-run",
        forbidden,
        replay_run=run,
        max_rpm=7,
    )
    assert replayed == summary
    for name in ("synthetic.jsonl", "faults.jsonl", "smoke_ids.txt"):
        assert (out.parent / name).read_bytes() == (
            replay_out.parent / name
        ).read_bytes()


def test_cli_prints_failure_summary_and_passes_max_rpm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typer.testing import CliRunner

    seen = []

    def completion(system: str, user: str, seed: int) -> dict[str, Any]:
        id = payload(user)["id"]
        return (
            {"choices": []}
            if id in {"syn-0001", "syn-0002", "syn-0003"}
            else response(user)
        )

    def client(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs["max_rpm"])
        return completion

    monkeypatch.setattr(synthetic, "GenerationClient", client)
    monkeypatch.setattr(synthetic, "load_dotenv", lambda: None)
    for name, value in (
        ("JUDGE_BASE_URL", "https://generation.invalid/v1"),
        ("JUDGE_MODEL", "fictional-model"),
        ("JUDGE_API_KEY", "test-key"),
    ):
        monkeypatch.setenv(name, value)
    run, out = tmp_path / "run", tmp_path / "public/synthetic.jsonl"
    result = CliRunner().invoke(
        synthetic.app,
        [
            "--n",
            "20",
            "--max-rpm",
            "7",
            "--out",
            str(out),
            "--run-dir",
            str(run),
        ],
    )
    assert result.exit_code == 1
    assert seen == [7]
    assert '"failure_summary"' in result.output and '"SCHEMA": 60' in result.output
    assert "more than 10% failed" in result.output
    assert not out.exists()

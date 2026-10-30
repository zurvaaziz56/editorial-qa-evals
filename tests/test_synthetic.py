"""Synthetic generation exercises mocked completions, never a live dataset/API."""

import json
from collections import Counter
from pathlib import Path
from random import Random
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from editorial_qa_evals.deterministic import load_rules, run_checks
from editorial_qa_evals.faults import RECIPES
from editorial_qa_evals.models import Entry
from editorial_qa_evals.synthetic import (
    Draft,
    GenerationClient,
    GenerationError,
    app,
    generate_dataset,
    inject_faults,
    plan_entries,
    render_draft,
    select_smoke,
    verify_faults,
)


def mocked_completion(system: str, user: str, seed: int) -> dict[str, Any]:
    payload, _ = json.JSONDecoder().raw_decode(user)
    assert "fictional" in system
    assert "injected_faults" not in payload and "human" not in payload
    items = [
        {
            "title": tip,
            "question": f"What supports {tip.lower()}?",
            "paragraphs": [
                "This fictional household leaves time for a pause. "
                "A familiar pattern supports the routine."
            ]
            * payload["paragraphs_per_item"],
        }
        for tip in payload["brief"]["tips"]
    ]
    return {"choices": [{"message": {"content": json.dumps({"items": items})}}]}


def clean_entry(kind: str = "simple_pitch_list") -> Entry:
    entry = next(p.entry for p in plan_entries(80, 7) if p.entry.piece_type == kind)
    payload = {
        **entry.model_dump(),
        "paragraphs_per_item": len(entry.approved_labels)
        if kind == "simple_pitch_list"
        else (1 if kind == "qa" else 2),
    }
    items = [
        {
            "title": tip,
            "question": f"What supports {tip.lower()}?",
            "paragraphs": ["A familiar rhythm supports rest. Quiet pauses help."]
            * payload["paragraphs_per_item"],
        }
        for tip in entry.brief.tips
    ]
    return render_draft(entry, Draft.model_validate({"items": items}))


@pytest.mark.parametrize("n", [20, 21, 40, 80, 100])
@pytest.mark.parametrize("seed", [7, 173, 204, 310])
def test_seeded_plan_and_strata(n: int, seed: int) -> None:
    plans = plan_entries(n, seed)
    assert plans == plan_entries(n, seed)
    assert len(plans) == n
    assert len({plan.entry.id for plan in plans}) == n
    assert abs(Counter(p.entry.region for p in plans)["UK"] - n / 2) <= 0.5
    assert sum(p.intended_verdict == "READY" for p in plans) == round(n / 4)
    assert {(p.entry.piece_type, p.intended_verdict) for p in plans} == {
        (kind, verdict)
        for kind in ("qa", "cpr", "simple_pitch_list")
        for verdict in ("READY", "REVISE", "MAJOR")
    }
    assert all(len(p.entry.brief.tips) == 5 for p in plans)
    if n == 80:
        assert Counter(p.entry.piece_type for p in plans) == {
            "simple_pitch_list": 45,
            "qa": 20,
            "cpr": 15,
        }


@pytest.mark.parametrize("kind", ["simple_pitch_list", "qa", "cpr"])
def test_rendered_clean_baseline(kind: str) -> None:
    entry = clean_entry(kind)
    assert not [result for result in run_checks(entry) if result.result == "fail"]
    if kind == "cpr":
        assert entry.body.count("https://source.invalid/") == 5
        assert "fictional simulation" in entry.body
    if kind == "qa":
        assert len(entry.questions) == len(entry.answers) == 5


def test_complete_mocked_generation_and_replay(tmp_path: Path) -> None:
    out, provenance = tmp_path / "public/synthetic.jsonl", tmp_path / "run"
    summary = generate_dataset(80, 7, out, provenance, mocked_completion)
    assert summary["types"] == {"simple_pitch_list": 45, "qa": 20, "cpr": 15}
    assert summary["regions"] == {"UK": 40, "US": 40}
    assert summary["clean"] == 20
    public = [json.loads(line) for line in out.read_text().splitlines()]
    faults = [
        json.loads(line)
        for line in out.with_name("faults.jsonl").read_text().splitlines()
    ]
    assert all("injected_faults" not in row and "human" not in row for row in public)
    assert all(0 <= len(row["recipes"]) <= 3 for row in faults)
    assert {len(row["recipes"]) for row in faults} == {0, 1, 2, 3}
    assert all(
        row["intended_verdict"] == "READY" for row in faults if not row["recipes"]
    )
    by_id = {row["id"]: row for row in faults}
    actual = {row["id"]: row for row in public}
    rules = load_rules()
    for row in public:
        verify_faults(Entry.model_validate(row), by_id[row["id"]]["recipes"], rules)
    ids = out.with_name("smoke_ids.txt").read_text().splitlines()
    assert len(ids) == len(set(ids)) == 20
    assert {
        (actual[id]["piece_type"], by_id[id]["intended_verdict"]) for id in ids
    } == {
        (kind, verdict)
        for kind in ("qa", "cpr", "simple_pitch_list")
        for verdict in ("READY", "REVISE", "MAJOR")
    }
    assert all(
        counts["missed"] == 0 for counts in summary["deterministic_confusion"].values()
    )
    assert len(list((provenance / "raw").glob("*.json"))) == 80

    def forbidden(system: str, user: str, seed: int) -> dict[str, Any]:
        pytest.fail("Replay must never call a model")

    replay_out = tmp_path / "replayed/synthetic.jsonl"
    replay_summary = generate_dataset(
        80, 7, replay_out, tmp_path / "replay-run", forbidden, replay_run=provenance
    )
    assert replay_summary == summary
    for name in ("synthetic.jsonl", "smoke_ids.txt", "faults.jsonl"):
        assert (out.parent / name).read_bytes() == (
            replay_out.parent / name
        ).read_bytes()


def test_invalid_drafts_retry_without_public_outputs(tmp_path: Path) -> None:
    calls = []

    def invalid(system: str, user: str, seed: int) -> dict[str, Any]:
        calls.append(user)
        return {"choices": [{"message": {"content": '{"items": []}'}}]}

    out = tmp_path / "out/synthetic.jsonl"
    with pytest.raises(GenerationError, match="three attempts"):
        generate_dataset(20, 7, out, tmp_path / "run", invalid)
    assert len(calls) == 3
    assert not out.exists()
    assert not out.with_name("faults.jsonl").exists()
    assert "failed validation" in calls[1]


def test_clean_failure_is_repaired_by_retry(tmp_path: Path) -> None:
    calls = 0

    def repair(system: str, user: str, seed: int) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        response = mocked_completion(system, user, seed)
        if calls == 1:
            response["choices"][0]["message"]["content"] = response["choices"][0][
                "message"
            ]["content"].replace("This fictional", "This—fictional")
        return response

    generate_dataset(20, 7, tmp_path / "data/synthetic.jsonl", tmp_path / "run", repair)
    assert calls == 21


def test_injection_invariants_across_many_combinations() -> None:
    rules = load_rules()
    for kind in ("qa", "cpr", "simple_pitch_list"):
        clean = clean_entry(kind)
        for seed in range(30):
            for verdict in ("REVISE", "MAJOR"):
                changed, names = inject_faults(clean, verdict, Random(seed), rules)
                assert 1 <= len(names) <= 3
                assert (
                    len(set(names) & {"count_plus", "count_minus", "dropped_tip"}) <= 1
                )
                assert (
                    max(
                        (RECIPES[name].intended_verdict for name in names),
                        key=("READY", "REVISE", "MAJOR").index,
                    )
                    == verdict
                )
                verify_faults(changed, names, rules)


def test_missing_deterministic_detection_is_a_hard_failure() -> None:
    with pytest.raises(GenerationError, match="Undetected.*C8.*confusion"):
        verify_faults(clean_entry(), ["em_dash"], load_rules())


def test_smoke_missing_stratum_is_rejected() -> None:
    entry = clean_entry()
    with pytest.raises(GenerationError, match="Missing intended smoke stratum"):
        select_smoke([entry], {entry.id: "READY"}, 7)


def test_replay_and_existing_run_guards(tmp_path: Path) -> None:
    out, run = tmp_path / "data/synthetic.jsonl", tmp_path / "run"
    generate_dataset(20, 7, out, run, mocked_completion)
    with pytest.raises(GenerationError, match="new or empty"):
        generate_dataset(20, 7, out, run, mocked_completion)
    with pytest.raises(GenerationError, match="Replay configuration"):
        generate_dataset(
            20, 8, out, tmp_path / "other", mocked_completion, replay_run=run
        )
    with pytest.raises(GenerationError, match="at least 20"):
        plan_entries(10, 7)


def test_http_client_is_provider_neutral_and_retries() -> None:
    requests = []
    delays = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429)
        return httpx.Response(
            200,
            json=mocked_completion(
                "fictional",
                json.dumps(
                    {"brief": {"tips": ["Quiet pause"] * 5}, "paragraphs_per_item": 1}
                ),
                7,
            ),
        )

    client = GenerationClient(
        "https://generation.invalid/v1",
        "fictional-model",
        "test-key",
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    )
    client("system", "user", 7)
    assert delays == [1]
    assert str(requests[0].url) == "https://generation.invalid/v1/chat/completions"
    assert requests[0].headers["Authorization"] == "Bearer test-key"
    payload = json.loads(requests[0].content)
    assert payload["temperature"] == 0
    assert "seed" not in payload


@pytest.mark.parametrize("status", [401, 403, 500])
def test_http_failures_are_sanitized(status: int) -> None:
    client = GenerationClient(
        "https://generation.invalid/v1",
        "fictional-model",
        "test-key",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="sensitive provider body")
        ),
        sleep=lambda _: None,
    )
    with pytest.raises(GenerationError, match=f"HTTP {status}") as error:
        client("system", "user", 7)
    assert "sensitive" not in str(error.value)
    assert "test-key" not in str(error.value)


def test_cli_missing_secrets_fails_before_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("editorial_qa_evals.synthetic.load_dotenv", lambda: None)
    for name in ("JUDGE_BASE_URL", "JUDGE_MODEL", "JUDGE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    result = CliRunner().invoke(
        app, ["--n", "20", "--out", str(tmp_path / "synthetic.jsonl")]
    )
    assert result.exit_code == 1
    assert "repository secrets" in result.output
    assert not (tmp_path / "synthetic.jsonl").exists()


@pytest.mark.parametrize("filename", ["faults.jsonl", "smoke_ids.txt"])
def test_reserved_output_paths_are_rejected(tmp_path: Path, filename: str) -> None:
    with pytest.raises(GenerationError, match="reserved sidecar"):
        generate_dataset(
            20, 7, tmp_path / filename, tmp_path / "run", mocked_completion
        )
    assert not (tmp_path / "run").exists()


def test_output_and_provenance_cannot_overlap(tmp_path: Path) -> None:
    with pytest.raises(GenerationError, match="overlap provenance"):
        generate_dataset(
            20, 7, tmp_path / "run/synthetic.jsonl", tmp_path / "run", mocked_completion
        )
    assert not (tmp_path / "run").exists()


def test_source_hashes_protect_replay(tmp_path: Path) -> None:
    run = tmp_path / "run"
    generate_dataset(20, 7, tmp_path / "public/synthetic.jsonl", run, mocked_completion)
    hashes = json.loads((run / "source_hashes.json").read_text())
    hashes["src/editorial_qa_evals/faults.py"] = "modified"
    (run / "source_hashes.json").write_text(json.dumps(hashes))
    with pytest.raises(GenerationError, match="source hashes differ"):
        generate_dataset(
            20,
            7,
            tmp_path / "replay/synthetic.jsonl",
            tmp_path / "replay-run",
            mocked_completion,
            replay_run=run,
        )


def test_incompatible_semantic_recipes_do_not_combine() -> None:
    rules = load_rules()
    clean = clean_entry("qa")
    for seed in range(80):
        _, names = inject_faults(clean, "MAJOR", Random(seed), rules)
        assert not set(names) >= {"dropped_tip", "bundled_q5"}
        assert not set(names) >= {"count_minus", "bundled_q5"}


def test_generation_sidecar_reconciles_after_complete_mock_labeling(
    tmp_path: Path,
) -> None:
    from editorial_qa_evals.reconcile import reconcile_faults

    out = tmp_path / "public/synthetic.jsonl"
    generate_dataset(20, 7, out, tmp_path / "run", mocked_completion)
    public = [json.loads(line) for line in out.read_text().splitlines()]
    for row in public:
        row["human"] = {
            "checks": {f"C{i}": "pass" for i in range(1, 14)},
            "judgment": {f"J{i}": "pass" for i in range(1, 8)},
            "routing": "none",
            "verdict": "READY",
            "notes": "Mocked labels only",
            "labeled_at": "2026-01-01T00:00:00Z",
            "labeler": "r1",
            "pass_number": 1,
        }
    labeled = tmp_path / "labeled.jsonl"
    labeled.write_text("".join(json.dumps(row) + "\n" for row in public))
    reconciled = tmp_path / "reconciled.jsonl"
    assert reconcile_faults(out.with_name("faults.jsonl"), labeled, reconciled) == 20
    faults = {
        row["id"]: row
        for row in map(
            json.loads, out.with_name("faults.jsonl").read_text().splitlines()
        )
    }
    for row in map(json.loads, reconciled.read_text().splitlines()):
        assert row["injected_faults"] == faults[row["id"]]["injected_faults"]
        assert "recipes" not in row and "intended_verdict" not in row


@pytest.mark.parametrize("status,body", [(200, "not-json"), (502, "server error")])
def test_invalid_http_responses_fail_without_leaking(status: int, body: str) -> None:
    client = GenerationClient(
        "https://generation.invalid/v1",
        "fictional-model",
        "test-key",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text=body)
        ),
        sleep=lambda _: None,
    )
    with pytest.raises(GenerationError) as error:
        client("system", "user", 7)
    assert body not in str(error.value)


def test_transport_failure_retries_are_bounded() -> None:
    attempts = []

    def fail(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        raise httpx.ConnectError("sensitive transport details", request=request)

    client = GenerationClient(
        "https://generation.invalid/v1",
        "fictional-model",
        "test-key",
        transport=httpx.MockTransport(fail),
        sleep=lambda _: None,
    )
    with pytest.raises(GenerationError, match="transport failed") as error:
        client("system", "user", 7)
    assert len(attempts) == 3
    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://generation.invalid",
        "https://user:secret@generation.invalid",
        "https://generation.invalid/?key=secret",
        "https://generation.invalid/#secret",
    ],
)
def test_endpoint_configuration_rejects_credentials_and_non_http(url: str) -> None:
    with pytest.raises(GenerationError, match="API root"):
        GenerationClient(url, "fictional-model", "test-key")


def test_prompt_and_label_table_match_public_contract() -> None:
    import yaml

    from editorial_qa_evals.synthetic import ROOT

    prompt = (ROOT / "prompts/synthetic/generate_body.md").read_text()
    metadata = yaml.safe_load(prompt.split("---", 2)[1])
    assert metadata["name"] == "synthetic-clean-body"
    assert metadata["version"] == "1.0"
    assert len(metadata["checks"]) == 20
    labels = yaml.safe_load((ROOT / "rules/labels.yaml").read_text())["labels"]
    assert labels["mistakes"] == ["Why it's a mistake", "What to do instead"]
    assert labels["waste of money"][-1] == "Savings"


def test_count_minus_cannot_remove_a_recorded_bundled_question() -> None:
    clean = clean_entry("qa")
    changed, names = inject_faults(clean, "MAJOR", Random(282), load_rules())
    assert not set(names) >= {"count_minus", "bundled_q5"}
    if "bundled_q5" in names:
        assert len(changed.questions) >= 5
        assert clean.brief.tips[3] in changed.questions[4]
        assert clean.brief.tips[4] in changed.questions[4]

"""Reliability regressions use mocked HTTP and model responses only."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_generation_client import FakeClock, user_prompt
from test_generation_recovery import payload, response

from editorial_qa_evals import synthetic
from editorial_qa_evals.brief_catalog import load_catalog, validate_brief
from editorial_qa_evals.generation_client import GenerationClient
from editorial_qa_evals.generation_errors import DeadlineReached, GenerationError


def request_brief(count: int = 7, kind: str = "cpr", id: str = "syn-0001") -> str:
    value = json.loads(user_prompt())
    value.update(id=id, piece_type=kind, brief={"tips": ["A tip"] * count})
    return json.dumps(value)


@pytest.mark.parametrize("failure", [400, "length"])
def test_recovery_changes_format_then_budget_once(failure: Any) -> None:
    sent = []
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        if len(sent) <= 2:
            if failure == 400:
                return httpx.Response(400, json={"error": {"code": "bad_output"}})
            return httpx.Response(200, json={"choices": [{"finish_reason": "length"}]})
        return httpx.Response(200, json={"choices": []})

    client = GenerationClient(
        "https://generation.invalid/v1",
        "openai/gpt-oss-120b",
        "test-key",
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleep=clock.sleep,
    )
    client("system", request_brief(), 7)
    assert [p["response_format"]["type"] for p in sent] == [
        "json_schema",
        "json_object",
        "json_object",
    ]
    assert [p["max_tokens"] for p in sent] == [6948, 6948, 8000]
    assert all(p["reasoning_effort"] == "low" for p in sent)
    assert len({json.dumps(p, sort_keys=True) for p in sent}) == 3


def test_persistent_400_stops_after_three_distinct_shapes() -> None:
    sent = []
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"code": "invalid_request"}})

    client = GenerationClient(
        "https://generation.invalid/v1",
        "model",
        "test-key",
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleep=clock.sleep,
    )
    with pytest.raises(GenerationError, match="HTTP 400"):
        client("system", request_brief(), 7)
    with pytest.raises(GenerationError):
        client("system", request_brief() + "feedback", 7)
    assert len(sent) == 3
    assert len(client.events) == 0  # Second call makes no new HTTP request.


@pytest.mark.parametrize(
    "count,kind,expected",
    [(3, "qa", 3548), (5, "simple_pitch_list", 4548), (7, "cpr", 6948)],
)
def test_budget_comes_from_brief(count: int, kind: str, expected: int) -> None:
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={})

    client = GenerationClient(
        "https://generation.invalid/v1",
        "model",
        "key",
        transport=httpx.MockTransport(handler),
    )
    client("system", request_brief(count, kind), 7)
    assert sent[0]["max_tokens"] == expected
    assert "reasoning_effort" not in sent[0]


def test_429_cooldown_survives_return_to_caller() -> None:
    clock = FakeClock()
    times = []

    def handler(request: httpx.Request) -> httpx.Response:
        times.append(clock())
        if len(times) < 3:
            return httpx.Response(429, headers={"Retry-After": "20"}, json={})
        return httpx.Response(200, json={})

    client = GenerationClient(
        "https://generation.invalid/v1",
        "model",
        "key",
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleep=clock.sleep,
    )
    with pytest.raises(GenerationError, match="429"):
        client("system", request_brief(), 7)
    client("system", request_brief() + "\nfeedback", 7)
    assert times == [0, 20, 40]
    assert client._interval == 6.75


def test_retry_after_http_date() -> None:
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=90))
    delay = GenerationClient._retry_delay(
        httpx.Response(429, headers={"Retry-After": future}), 0
    )
    assert 88 < delay <= 90


def test_identical_request_and_global_entry_budgets() -> None:
    clock = FakeClock()
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={})

    client = GenerationClient(
        "https://generation.invalid/v1",
        "model",
        "key",
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleep=clock.sleep,
    )
    for i in range(8):
        client("system", request_brief() + f"\nfeedback {i}", 7)
    with pytest.raises(GenerationError, match="budget"):
        client("system", request_brief() + "different", 7)
    assert len(sent) == 8
    other = request_brief(id="syn-0002")
    client("system", other, 7)
    client("system", other, 7)
    with pytest.raises(GenerationError, match="identical"):
        client("system", other, 7)
    assert len(sent) == 10


def test_error_body_redaction_limit_and_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = FakeClock()
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    counts: Counter[str] = Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        user = sent["messages"][1]["content"]
        id = payload(user)["id"]
        counts[id] += 1
        if counts[id] == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": "schema_rejected",
                        "message": "test-key Bearer hidden-token "
                        "https://user:pass@host.invalid/?token=secret " + "é" * 3000,
                    }
                },
            )
        return httpx.Response(200, json=response(user))

    client = GenerationClient(
        "https://generation.invalid/v1",
        "model",
        "test-key",
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleep=clock.sleep,
    )
    run = tmp_path / "run"
    summary = synthetic.generate_dataset(
        20, 7, tmp_path / "public/synthetic.jsonl", run, client, clock=clock
    )
    assert summary["http_status_failures"] == {"400": 20}
    assert summary["provider_error_failures"] == {"schema_rejected": 20}
    assert '"400": 20' in summary_path.read_text()
    records = [
        json.loads(p.read_text()) for p in (run / "attempts").glob("*-http-*.json")
    ]
    assert len(records) == 20
    for record in records:
        body = record["provider_error_body"]
        assert len(body.encode()) <= 2048
        assert not any(
            s in body for s in ("test-key", "hidden-token", "user:pass", "token=secret")
        )


def test_deadline_during_retry_leaves_time_to_checkpoint() -> None:
    clock = FakeClock()
    client = GenerationClient(
        "https://generation.invalid/v1",
        "model",
        "key",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(429, headers={"Retry-After": "120"})
        ),
        clock=clock,
        sleep=clock.sleep,
    )
    client.deadline = 60
    with pytest.raises(DeadlineReached):
        client("system", request_brief(), 7)
    assert clock() == 0
    assert client.states["syn-0001"]["requests"] == 1


def test_checkpoint_deadline_resume_and_seed_guard(tmp_path: Path) -> None:
    clock = FakeClock()
    run = tmp_path / "first"
    calls = []

    def completion(system: str, user: str, seed: int) -> dict[str, Any]:
        calls.append(payload(user)["id"])
        if len(calls) > 1:
            saved = json.loads((run / "checkpoint.json").read_text())
            assert len(saved["completed"]) == len(calls) - 1
        clock.current += 20
        return response(user)

    out = tmp_path / "partial/synthetic.jsonl"
    partial = synthetic.generate_dataset(
        20, 7, out, run, completion, deadline_minutes=1, clock=clock
    )
    assert partial["deadline_reached"] and partial["entries"] == 3
    assert len(out.read_text().splitlines()) == 3
    checkpoint = run / "checkpoint.json"
    resumed_calls = []

    def resume_completion(system: str, user: str, seed: int) -> dict[str, Any]:
        resumed_calls.append(payload(user)["id"])
        return response(user)

    final = tmp_path / "final/synthetic.jsonl"
    result = synthetic.generate_dataset(
        20, 7, final, tmp_path / "resumed", resume_completion, resume=checkpoint
    )
    assert result["entries"] == 20

    def forbidden(*args: Any) -> dict[str, Any]:
        pytest.fail("Replay of a resumed run called a model")

    replayed = synthetic.generate_dataset(
        20,
        7,
        tmp_path / "resume-replay/out.jsonl",
        tmp_path / "resume-replay-run",
        forbidden,
        replay_run=tmp_path / "resumed",
    )
    assert replayed == result
    assert not set(calls) & set(resumed_calls)
    full = tmp_path / "full/synthetic.jsonl"
    synthetic.generate_dataset(20, 7, full, tmp_path / "full-run", resume_completion)
    assert full.read_bytes() == final.read_bytes()
    assert (
        full.with_name("faults.jsonl").read_bytes()
        == final.with_name("faults.jsonl").read_bytes()
    )
    with pytest.raises(GenerationError, match="Resume configuration"):
        synthetic.generate_dataset(
            20,
            8,
            tmp_path / "wrong/out.jsonl",
            tmp_path / "wrong-run",
            resume_completion,
            resume=checkpoint,
        )


def test_brief_counterexamples_and_catalog_cross_product() -> None:
    catalog = load_catalog()
    plans = synthetic.plan_entries(80, 7)
    pet = next(p.entry for p in plans if p.entry.brief.domain == "pets")
    for title in (
        "Veterinary nurse warns of 7 habits in pet health and care",
        f"{pet.brief.expert.credential} warns of "
        f"{len(pet.brief.tips)} habits for dog owners",
    ):
        wrong = pet.model_copy(deep=True)
        wrong.brief.noun_category = "habits"
        wrong.task_name = title
        with pytest.raises(GenerationError):
            validate_brief(wrong)
    wrong_count = pet.model_copy(
        update={
            "task_name": pet.task_name.replace(
                str(len(pet.brief.tips)), str(10 + len(pet.brief.tips)), 1
            )
        }
    )
    with pytest.raises(GenerationError, match="count"):
        validate_brief(wrong_count)
    for plan in plans:
        validate_brief(plan.entry, catalog)
    good = next(p.entry for p in plans if p.entry.brief.noun_category == "habits")
    bad = good.model_copy(deep=True)
    bad.brief.tips[0] = "Skipping a beneficial routine"
    with pytest.raises(GenerationError, match="Tips"):
        validate_brief(bad)
    bad = good.model_copy(
        update={"task_name": good.task_name.replace("habits", "bad habits")}
    )
    with pytest.raises(GenerationError):
        validate_brief(bad)


def test_invalid_brief_rejected_before_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plans = synthetic.plan_entries(20, 7)
    plans[
        0
    ].entry.task_name = "Veterinary nurse warns of 7 habits in pet health and care"
    monkeypatch.setattr(synthetic, "plan_entries", lambda n, seed: plans)

    def forbidden(*args: Any) -> dict[str, Any]:
        pytest.fail("Invalid brief reached model")

    with pytest.raises(GenerationError):
        synthetic.generate_dataset(
            20, 7, tmp_path / "public/out.jsonl", tmp_path / "run", forbidden
        )


def test_http_retries_share_the_entry_budget_and_later_ids_run(tmp_path: Path) -> None:
    clock = FakeClock()
    counts: Counter[str] = Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        user = json.loads(request.content)["messages"][1]["content"]
        id = payload(user)["id"]
        counts[id] += 1
        if id == "syn-0001":
            return httpx.Response(503, json={"error": {"code": "unavailable"}})
        return httpx.Response(200, json=response(user))

    client = GenerationClient(
        "https://generation.invalid/v1",
        "model",
        "key",
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleep=clock.sleep,
    )
    summary = synthetic.generate_dataset(
        20,
        7,
        tmp_path / "public/out.jsonl",
        tmp_path / "run",
        client,
        clock=clock,
    )
    assert counts["syn-0001"] == 8
    assert len(counts) == 20
    assert summary["http_status_failures"] == {"503": 8}
    assert summary["failed_ids"] == ["syn-0001"]


def test_nested_credentials_are_redacted() -> None:
    client = GenerationClient("https://generation.invalid/v1", "model", "api-key-value")
    record = client._error(
        httpx.Response(
            400,
            json={
                "error": {
                    "code": "invalid_request",
                    "details": {
                        "Authorization": "Basic encoded-credential",
                        "api_key": "another credential with spaces",
                        "nested": [{"access_token": "hidden-access"}],
                    },
                    "message": "api-key-value https://host.invalid/?key=hidden",
                },
            },
        )
    )
    assert record["provider_error_code"] == "invalid_request"
    assert not any(
        value in record["provider_error_body"]
        for value in (
            "encoded-credential",
            "another credential",
            "hidden-access",
            "api-key-value",
            "?key=hidden",
        )
    )


def test_terminal_400_and_deadline_runs_replay_offline(tmp_path: Path) -> None:
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        user = json.loads(request.content)["messages"][1]["content"]
        if payload(user)["id"] == "syn-0001":
            return httpx.Response(400, json={"error": {"code": "invalid_request"}})
        return httpx.Response(200, json=response(user))

    client = GenerationClient(
        "https://generation.invalid/v1",
        "model",
        "key",
        transport=httpx.MockTransport(handler),
        clock=clock,
        sleep=clock.sleep,
    )
    out, run = tmp_path / "public/out.jsonl", tmp_path / "run"
    summary = synthetic.generate_dataset(20, 7, out, run, client, clock=clock)

    def forbidden(*args: Any) -> dict[str, Any]:
        pytest.fail("Replay requested a model")

    replayed = synthetic.generate_dataset(
        20,
        7,
        tmp_path / "replayed/out.jsonl",
        tmp_path / "replay-run",
        forbidden,
        replay_run=run,
    )
    assert replayed == summary
    assert summary["http_status_failures"] == {"400": 3}
    assert (tmp_path / "replayed/out.jsonl").read_bytes() == out.read_bytes()

    def completion(system: str, user: str, seed: int) -> dict[str, Any]:
        clock.current += 20
        return response(user)

    partial_out, partial_run = tmp_path / "partial/out.jsonl", tmp_path / "partial-run"
    partial = synthetic.generate_dataset(
        20, 7, partial_out, partial_run, completion, deadline_minutes=1, clock=clock
    )
    replayed_partial = synthetic.generate_dataset(
        20,
        7,
        tmp_path / "partial-replay/out.jsonl",
        tmp_path / "partial-replay-run",
        forbidden,
        replay_run=partial_run,
    )
    assert replayed_partial == partial

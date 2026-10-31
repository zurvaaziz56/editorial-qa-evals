"""Mocked schema negotiation, rate limiting and transient API failures."""

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from editorial_qa_evals.generation_client import GenerationClient
from editorial_qa_evals.generation_errors import GenerationError


@dataclass
class FakeClock:
    current: float = 0.0
    delays: list[float] = field(default_factory=list)

    def __call__(self) -> float:
        return self.current

    def sleep(self, duration: float) -> None:
        assert duration >= 0
        self.delays.append(duration)
        self.current += duration


def user_prompt(required: int = 2) -> str:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "paragraphs", "question"],
                    "properties": {
                        "title": {"type": "string"},
                        "question": {"type": "string"},
                        "paragraphs": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": required,
                            "maxItems": required,
                        },
                    },
                },
            }
        },
    }
    return json.dumps({"response_schema": schema})


def client_with(
    handler: Any, clock: FakeClock, max_rpm: float = 20
) -> GenerationClient:
    return GenerationClient(
        "https://generation.invalid/v1",
        "fictional-model",
        "test-key",
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        max_rpm=max_rpm,
        clock=clock,
    )


def test_strict_schema_uses_the_current_entry_paragraph_count() -> None:
    payloads = []
    times = []
    clock = FakeClock()

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        times.append(clock())
        return httpx.Response(200, json={"choices": []})

    client = client_with(handler, clock)
    client("system", user_prompt(2) + "\nPrevious check C8 failed.", 7)
    client("system", user_prompt(3), 7)
    assert times == [0, 3]
    assert clock.delays == [3]
    for payload, required in zip(payloads, (2, 3), strict=True):
        format = payload["response_format"]
        assert format["type"] == "json_schema"
        assert format["json_schema"]["strict"] is True
        paragraphs = format["json_schema"]["schema"]["properties"]["items"]["items"][
            "properties"
        ]["paragraphs"]
        assert paragraphs["minItems"] == paragraphs["maxItems"] == required
        assert payload["max_tokens"] == 2048
        assert payload["temperature"] == 0
        assert "seed" not in payload


@pytest.mark.parametrize("status", [400, 404, 422, 501])
def test_unsupported_strict_schema_falls_back_once_and_is_cached(status: int) -> None:
    clock = FakeClock()
    formats = []
    times = []

    def handler(request: httpx.Request) -> httpx.Response:
        formats.append(json.loads(request.content)["response_format"]["type"])
        times.append(clock())
        if len(formats) == 1:
            return httpx.Response(
                status,
                json={
                    "error": {"message": "json_schema response_format not supported"}
                },
            )
        return httpx.Response(200, json={"choices": []})

    client = client_with(handler, clock)
    client("system", user_prompt(), 7)
    client("system", user_prompt(), 7)
    assert formats == ["json_schema", "json_object", "json_object"]
    assert times == [0, 3, 6]


@pytest.mark.parametrize(
    "status,message",
    [
        (401, "json_schema not supported; sensitive auth details"),
        (403, "json_schema not supported"),
        (400, "Invalid schema in response_format: required must contain title"),
        (422, "Invalid JSON schema with unsupported keyword"),
        (400, "Unrelated model configuration is unsupported"),
        (400, "Malformed request"),
        (404, "Not found"),
        (404, "The requested model was not found"),
    ],
)
def test_other_errors_do_not_downgrade_schema(status: int, message: str) -> None:
    clock = FakeClock()
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["response_format"]["type"])
        return httpx.Response(status, json={"error": {"message": message}})

    client = client_with(handler, clock)
    with pytest.raises(GenerationError, match=f"HTTP {status}") as error:
        client("system", user_prompt(), 7)
    assert seen == ["json_schema"]
    assert message not in str(error.value)
    assert "test-key" not in str(error.value)


def test_retries_and_subsequent_calls_all_obey_the_same_rate_limit() -> None:
    clock = FakeClock()
    times = []
    statuses = iter([429, 503, 200, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        times.append(clock())
        return httpx.Response(next(statuses), json={"choices": []})

    client = client_with(handler, clock)
    client("system", user_prompt(), 7)
    client("system", user_prompt(), 7)
    assert times == [0, 3, 6, 9]
    assert clock.delays == [1, 2, 2, 1, 3]


def test_custom_rpm_changes_minimum_request_spacing() -> None:
    clock = FakeClock()
    times = []

    def handler(request: httpx.Request) -> httpx.Response:
        times.append(clock())
        return httpx.Response(200, json={})

    client = client_with(handler, clock, max_rpm=10)
    for _ in range(3):
        client("system", user_prompt(), 7)
    assert times == [0, 6, 12]


def test_numeric_retry_after_does_not_shorten_backoff() -> None:
    clock = FakeClock()
    times = []

    def handler(request: httpx.Request) -> httpx.Response:
        times.append(clock())
        if len(times) == 1:
            return httpx.Response(429, headers={"Retry-After": "8"})
        return httpx.Response(200, json={})

    client = client_with(handler, clock)
    client("system", user_prompt(), 7)
    assert times == [0, 8]


def test_transport_retries_are_bounded_without_printing_provider_details() -> None:
    clock = FakeClock()
    times = []

    def handler(request: httpx.Request) -> httpx.Response:
        times.append(clock())
        raise httpx.ConnectError("sensitive transport message", request=request)

    client = client_with(handler, clock)
    with pytest.raises(GenerationError, match="three attempts") as error:
        client("system", user_prompt(), 7)
    assert times == [0, 3, 6]
    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize("body", ["not json", "[]"])
def test_success_status_still_requires_object_json(body: str) -> None:
    clock = FakeClock()
    client = client_with(lambda request: httpx.Response(200, text=body), clock)
    with pytest.raises(GenerationError, match="JSON"):
        client("system", user_prompt(), 7)


@pytest.mark.parametrize("max_rpm", [0, -1, float("nan"), float("inf")])
def test_invalid_rate_limit_is_rejected(max_rpm: float) -> None:
    with pytest.raises(GenerationError, match="finite positive"):
        GenerationClient(
            "https://generation.invalid/v1",
            "fictional-model",
            "test-key",
            max_rpm=max_rpm,
        )


def test_missing_schema_uses_json_mode_without_claiming_provider_incompatibility() -> (
    None
):
    clock = FakeClock()
    formats = []

    def handler(request: httpx.Request) -> httpx.Response:
        formats.append(json.loads(request.content)["response_format"]["type"])
        return httpx.Response(200, json={})

    client = client_with(handler, clock)
    client("system", "plain JSON request", 7)
    client("system", user_prompt(), 7)
    assert formats == ["json_object", "json_schema"]


def test_strict_routing_capability_error_falls_back_once() -> None:
    clock = FakeClock()
    formats = []

    def handler(request: httpx.Request) -> httpx.Response:
        formats.append(json.loads(request.content)["response_format"]["type"])
        if len(formats) == 1:
            return httpx.Response(
                404,
                json={
                    "error": {
                        "message": (
                            "No endpoints found that support the requested parameters"
                        )
                    }
                },
            )
        return httpx.Response(200, json={"choices": []})

    client = client_with(handler, clock)
    client("system", user_prompt(), 7)
    client("system", user_prompt(), 7)
    assert formats == ["json_schema", "json_object", "json_object"]
    assert clock.delays == [3, 3]


@pytest.mark.parametrize("delay", [61, 120])
def test_long_retry_after_is_not_shortened(delay: int) -> None:
    clock = FakeClock()
    times = []

    def handler(request: httpx.Request) -> httpx.Response:
        times.append(clock())
        if len(times) == 1:
            return httpx.Response(429, headers={"Retry-After": str(delay)})
        return httpx.Response(200, json={})

    client_with(handler, clock)("system", user_prompt(), 7)
    assert times == [0, delay]


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_output_token_limit(limit: Any) -> None:
    with pytest.raises(GenerationError, match="max-tokens"):
        GenerationClient(
            "https://generation.invalid/v1", "model", "key", max_tokens=limit
        )


def test_custom_output_token_limit_is_sent() -> None:
    payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={})

    GenerationClient(
        "https://generation.invalid/v1",
        "model",
        "key",
        transport=httpx.MockTransport(handler),
        max_tokens=1024,
    )("system", user_prompt(), 7)
    assert payloads[0]["max_tokens"] == 1024

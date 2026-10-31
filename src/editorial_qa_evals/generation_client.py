"""Rate-limited chat generation with negotiated structured-output support."""

import json
import math
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from editorial_qa_evals.generation_errors import GenerationError


class GenerationClient:
    """Use strict per-entry schemas when supported, preserving local validation."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_rpm: float = 20,
        clock: Callable[[], float] = time.monotonic,
        max_tokens: int = 2048,
    ) -> None:
        url = urlsplit(base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise GenerationError(
                "JUDGE_BASE_URL needs an HTTP(S) API root without credentials/query"
            )
        if not model.strip() or not api_key.strip():
            raise GenerationError("JUDGE_MODEL and JUDGE_API_KEY must be configured")
        if not math.isfinite(max_rpm) or max_rpm <= 0:
            raise GenerationError("max-rpm must be a finite positive number")
        if (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or max_tokens <= 0
        ):
            raise GenerationError("max-tokens must be a positive integer")
        self.max_tokens = max_tokens
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self._transport = transport
        self._sleep = sleep
        self._clock = clock
        self._interval = 60.0 / max_rpm
        self._last_request: float | None = None
        self._schema_supported: bool | None = None

    def _wait_for_slot(self) -> None:
        if self._last_request is not None:
            delay = self._last_request + self._interval - self._clock()
            if delay > 0:
                self._sleep(delay)
        self._last_request = self._clock()

    def _response_format(self, user: str) -> dict[str, Any]:
        try:
            payload, _ = json.JSONDecoder().raw_decode(user.lstrip())
        except (TypeError, ValueError):
            payload = {}
        schema = payload.get("response_schema") if isinstance(payload, dict) else None
        if isinstance(schema, dict) and self._schema_supported is not False:
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": "synthetic_clean_body",
                    "strict": True,
                    "schema": schema,
                },
            }
        return {"type": "json_object"}

    @staticmethod
    def _unsupported_schema(response: httpx.Response) -> bool:
        """Negotiate capability errors only, never hide an invalid supplied schema."""
        if response.status_code not in {400, 404, 422, 501}:
            return False
        try:
            body = response.json()
        except ValueError:
            text = response.text[:8192]
        else:
            error = body.get("error", body) if isinstance(body, dict) else body
            if isinstance(error, dict):
                text = " ".join(
                    str(error.get(key, "")) for key in ("message", "param", "code")
                )
            else:
                text = str(error)
        text = text.casefold()
        if any(
            marker in text
            for marker in (
                "invalid schema",
                "invalid json schema",
                "invalid_json_schema",
                "schema is invalid",
                "schema validation",
                "schema must",
            )
        ):
            return False
        if response.status_code == 404 and (
            "no endpoints found that support the requested parameters" in text
        ):
            return True
        feature = any(
            marker in text
            for marker in ("response_format", "json_schema", "structured output")
        )
        unsupported = any(
            marker in text
            for marker in (
                "not supported",
                "unsupported",
                "does not support",
                "doesn't support",
                "not available",
                "not implemented",
                "unknown parameter",
                "unrecognized parameter",
                "only supports",
                "supports only",
            )
        )
        return feature and unsupported

    @staticmethod
    def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
        delay = float(2**attempt)
        if response is not None:
            try:
                retry_after = float(response.headers.get("Retry-After", ""))
            except ValueError:
                pass
            else:
                if math.isfinite(retry_after) and retry_after >= 0:
                    delay = max(delay, retry_after)
        return delay

    def __call__(self, system: str, user: str, seed: int) -> dict[str, Any]:
        # The local planner owns seeding. Saved raw responses provide exact replay;
        # a provider-specific seed parameter is not required for this client.
        with httpx.Client(transport=self._transport, timeout=90.0) as client:
            attempt = 0
            while attempt < 3:
                response_format = self._response_format(user)
                strict = response_format["type"] == "json_schema"
                self._wait_for_slot()
                try:
                    response = client.post(
                        self.base_url + "/chat/completions",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json={
                            "model": self.model,
                            "temperature": 0,
                            "max_tokens": self.max_tokens,
                            "response_format": response_format,
                            "messages": [
                                {"role": "system", "content": system},
                                {"role": "user", "content": user},
                            ],
                        },
                    )
                except httpx.TransportError:
                    if attempt == 2:
                        raise GenerationError(
                            "Generation transport failed after three attempts"
                        ) from None
                    self._sleep(self._retry_delay(None, attempt))
                    attempt += 1
                    continue
                if strict and self._unsupported_schema(response):
                    self._schema_supported = False
                    # Capability fallback is separate from transient retries and
                    # goes through the same global rate limiter as every request.
                    continue
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        self._sleep(self._retry_delay(response, attempt))
                        attempt += 1
                        continue
                if response.is_error:
                    raise GenerationError(
                        f"Generation API returned HTTP {response.status_code}"
                    )
                try:
                    result = response.json()
                except ValueError:
                    raise GenerationError(
                        "Generation API returned non-JSON content"
                    ) from None
                if not isinstance(result, dict):
                    raise GenerationError("Generation API returned non-object JSON")
                if strict:
                    self._schema_supported = True
                return result
        raise GenerationError("Generation request did not complete")

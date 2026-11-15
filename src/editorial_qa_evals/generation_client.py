"""Rate-limited chat generation with negotiated structured-output support."""

import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from editorial_qa_evals.generation_errors import DeadlineReached, GenerationError


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
            or max_tokens > 8000
        ):
            raise GenerationError("max-tokens must be a positive integer")
        self.max_tokens = max_tokens
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self._http = httpx.Client(transport=transport, timeout=90.0)
        self._sleep = sleep
        self._clock = clock
        self._interval = 60.0 / max_rpm
        self._last_request: float | None = None
        self._not_before = 0.0
        self._schema_supported: bool | None = None
        self.deadline: float | None = None
        self.events: list[dict[str, Any]] = []
        self.states: dict[str, dict[str, Any]] = {}

    def close(self) -> None:
        """Release the pooled HTTP connections after the generation run."""
        self._http.close()

    def _pause(self, delay: float) -> None:
        if self.deadline is not None and self._clock() + delay >= self.deadline:
            raise DeadlineReached("Generation deadline reached")
        self._sleep(delay)

    def _error(self, response: httpx.Response) -> dict[str, Any]:
        def redact(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: "[REDACTED]"
                    if re.search(
                        r"(?i)api.?key|authorization|token|secret|password|cookie", key
                    )
                    else redact(item)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [redact(item) for item in value]
            if isinstance(value, str):
                text = value.replace(self._api_key, "[REDACTED]")
                text = re.sub(
                    r"(?i)(?:bearer|basic)\s+[^\s\"']+", "[REDACTED_AUTH]", text
                )
                text = re.sub(r"https?://[^\s\"']+", "[REDACTED_URL]", text)
                return re.sub(
                    r"(?i)(api[_-]?key|authorization|token|secret|password)\s*[:=]\s*[^,;\n]+",
                    r"\1=[REDACTED]",
                    text,
                )
            return value

        try:
            text = json.dumps(redact(response.json()), ensure_ascii=False)
        except ValueError:
            text = redact(response.text)
        code = None
        try:
            error = response.json().get("error", {})
            if isinstance(error, dict):
                code = error.get("code") or error.get("type")
        except (ValueError, AttributeError):
            pass
        if code is not None and (
            not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", str(code))
            or self._api_key in str(code)
        ):
            code = "redacted"
        return {
            "http_status": response.status_code,
            "provider_error_code": str(code)[:128] if code is not None else "unknown",
            "provider_error_body": text.encode("utf-8")[:2048].decode(
                "utf-8", errors="ignore"
            ),
        }

    def _wait_for_slot(self) -> None:
        if self._not_before > self._clock():
            self._pause(self._not_before - self._clock())
        if self._last_request is not None:
            delay = self._last_request + self._interval - self._clock()
            if delay > 0:
                self._pause(delay)
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
                try:
                    date = parsedate_to_datetime(
                        response.headers.get("Retry-After", "")
                    )
                    delay = max(
                        delay, (date - datetime.now(timezone.utc)).total_seconds()
                    )
                except (TypeError, ValueError, OverflowError):
                    pass
            else:
                if math.isfinite(retry_after) and retry_after >= 0:
                    delay = max(delay, retry_after)
        return delay

    def __call__(self, system: str, user: str, seed: int) -> dict[str, Any]:
        try:
            brief, _ = json.JSONDecoder().raw_decode(user.lstrip())
        except ValueError:
            brief = {}
        key = brief.get("id", "anonymous")
        count = len(brief.get("brief", {}).get("tips", []))
        stats = count if brief.get("piece_type") == "cpr" else 0
        initial = min(8000, self.max_tokens + 500 * count + 200 * stats)
        state = self.states.setdefault(
            key,
            {
                "requests": 0,
                "json": False,
                "tokens": initial,
                "raised": False,
                "shapes": {},
                "blocked": False,
            },
        )
        self.events = []
        transient = 0
        while state["requests"] < 8 and not state["blocked"]:
            if self.deadline is not None and self._clock() >= self.deadline:
                raise DeadlineReached("Generation deadline reached")
            response_format = (
                {"type": "json_object"}
                if state["json"]
                else self._response_format(user)
            )
            payload = {
                "model": self.model,
                "temperature": 0,
                "max_tokens": state["tokens"],
                "response_format": response_format,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            if "gpt-oss" in self.model.casefold():
                payload["reasoning_effort"] = "low"
            shape = hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest()
            if state["shapes"].get(shape, 0) >= 2:
                raise GenerationError("Two identical requests already sent")
            self._wait_for_slot()
            state["requests"] += 1
            state["shapes"][shape] = state["shapes"].get(shape, 0) + 1
            timeout = (
                90.0
                if self.deadline is None
                else min(90.0, self.deadline - self._clock())
            )
            try:
                response = self._http.post(
                    self.base_url + "/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                    timeout=max(0.001, timeout),
                )
            except httpx.TransportError:
                self.events.append(
                    {
                        "http_status": None,
                        "provider_error_code": "transport",
                        "provider_error_body": "Transport failed",
                    }
                )
                transient += 1
                if transient >= 2:
                    raise GenerationError(
                        "Generation transport failed after two attempts"
                    ) from None
                self._pause(2 ** (transient - 1))
                continue
            if response.is_error:
                self.events.append(self._error(response))
            if response.status_code == 400:
                state["shapes"][shape] = 2
                if response_format["type"] == "json_schema":
                    state["json"] = True
                elif state["tokens"] < 8000 and not state["raised"]:
                    state["tokens"] = min(8000, state["tokens"] + 2048)
                    state["raised"] = True
                else:
                    state["blocked"] = True
                    raise GenerationError(
                        "Generation API returned HTTP 400; recovery exhausted"
                    )
                continue
            if response_format["type"] == "json_schema" and self._unsupported_schema(
                response
            ):
                self._schema_supported = False
                state["json"] = True
                continue
            if response.status_code == 429:
                self._interval *= 1.5
                self._not_before = self._clock() + self._retry_delay(
                    response, transient
                )
            if response.status_code == 429 or response.status_code >= 500:
                transient += 1
                if transient < 2:
                    self._pause(self._retry_delay(response, transient - 1))
                    continue
            if response.is_error:
                if response.status_code not in {429} and response.status_code < 500:
                    state["blocked"] = True
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
            choices = result.get("choices", [])
            if not isinstance(choices, list) or any(
                not isinstance(c, dict) for c in choices
            ):
                raise GenerationError("Generation API returned malformed choices")
            if any(c.get("finish_reason") == "length" for c in choices):
                if response_format["type"] == "json_schema":
                    state["json"] = True
                elif state["tokens"] < 8000 and not state["raised"]:
                    state["tokens"] = min(8000, state["tokens"] + 2048)
                    state["raised"] = True
                else:
                    state["blocked"] = True
                    raise GenerationError("Generation truncated at the 8000-token cap")
                continue
            return result
        raise GenerationError("Entry request budget exhausted (8 requests)")

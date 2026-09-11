"""Application-model client. See CONTRACTS.md §6. Talks to the Terminal gateway over HTTP."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

MODELS = ("lot-fast", "lot-deep")


class ModelUnavailable(Exception):
    """Raised when the gateway is in an outage window or unreachable."""


class ModelRequestError(Exception):
    """Raised for 4xx responses (bad model name, bad schema)."""


@dataclass(frozen=True)
class ModelResponse:
    content: str | dict[str, Any]
    model: str
    usage: dict[str, int]
    latency_ms: int
    request_id: str


def _interview_state() -> dict[str, Any]:
    """`./interview start|status` writes the platform's gateway URL + attempt token here so candidate code finds them without env setup."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(root, ".interview_state.json"), encoding="utf-8") as fh:
            st = json.load(fh)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


class ModelClient:
    def __init__(self, base_url: str | None = None, attempt_token: str | None = None, timeout: float = 20.0) -> None:
        st = _interview_state()
        self.base_url = (base_url or os.environ.get("MODEL_BASE_URL") or st.get("gateway_url") or "http://localhost:8081").rstrip("/")
        self.attempt_token = attempt_token or os.environ.get("ATTEMPT_TOKEN") or st.get("attempt_token") or "local-dev"
        self.timeout = timeout

    def complete(self, *, model: str, messages: list[dict[str, str]], response_schema: dict[str, Any] | None = None,
                 temperature: float = 0.0) -> ModelResponse:
        if model not in MODELS:
            raise ModelRequestError(f"unknown model {model!r}; use one of {MODELS}")
        body = json.dumps({"model": model, "messages": messages, "response_schema": response_schema,
                           "temperature": temperature}).encode()
        req = urllib.request.Request(f"{self.base_url}/v1/complete", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-Attempt-Token": self.attempt_token})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 503:
                raise ModelUnavailable("gateway outage") from exc
            detail = exc.read().decode(errors="replace")
            raise ModelRequestError(f"gateway {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise ModelUnavailable(f"gateway unreachable: {exc}") from exc
        return ModelResponse(content=data["content"], model=data["model"], usage=data.get("usage", {}),
                             latency_ms=int(data.get("latency_ms", (time.time() - t0) * 1000)),
                             request_id=data.get("request_id", ""))

    def set_outage(self, down: bool) -> None:
        """Harness-only: mirror a fixture `system.model_outage` event onto the gateway. Candidates never call this."""
        body = json.dumps({"attempt_token": self.attempt_token, "down": down}).encode()
        req = urllib.request.Request(f"{self.base_url}/v1/admin/force_outage", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=self.timeout).read()
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass

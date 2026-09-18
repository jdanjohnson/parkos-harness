"""Application-model client. See CONTRACTS.md §6.

Two providers behind one `complete()`:
  gateway  POST <MODEL_BASE_URL or .interview_state.json gateway_url>/v1/complete (the platform's lot-fast / lot-deep).
  cli      shell out to the candidate's own agent CLI on PATH (claude, codex, cursor-agent, gemini — see CLI_COMMANDS),
           used when the gateway is not configured / unreachable, or always with MODEL_PROVIDER=cli.
Env: MODEL_PROVIDER=auto|gateway|cli (default auto) · MODEL_CLI=<name> forces one CLI, MODEL_CLI=none disables the CLI
provider (the hidden evaluator sets this) · MODEL_BASE_URL / ATTEMPT_TOKEN as before.
Every failure a caller should degrade on — no gateway, no CLI, CLI error or timeout, no JSON in a JSON-only reply — is
ModelUnavailable; ModelRequestError stays for caller mistakes (unknown model name, gateway 4xx)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

MODELS = ("lot-fast", "lot-deep")

# Agent CLIs in the order they are tried; {prompt} is replaced by the whole prompt as ONE argv element.
CLI_COMMANDS: dict[str, tuple[str, ...]] = {
    "claude": ("claude", "-p", "{prompt}", "--output-format", "text"),
    "codex": ("codex", "exec", "{prompt}"),
    "cursor-agent": ("cursor-agent", "-p", "{prompt}"),
    "gemini": ("gemini", "-p", "{prompt}"),
}
CLI_TIMEOUT_S = 120.0
JSON_INSTRUCTION = "Reply with only JSON matching this schema: "


class ModelUnavailable(Exception):
    """Raised when no provider can answer: gateway outage/unreachable, no agent CLI on PATH, CLI failed or timed out."""

    def __init__(self, msg: str = "", *, outage: bool = False) -> None:
        super().__init__(msg)
        self.outage = outage  # True for a configured gateway outage (503): the degradation path, never CLI fallback


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


def find_cli(env: dict[str, str] | None = None) -> str | None:
    """Name of the agent CLI to use, or None. MODEL_CLI forces one (or "none" to disable); otherwise the first of CLI_COMMANDS on PATH."""
    env = os.environ if env is None else env
    forced = (env.get("MODEL_CLI") or "").strip()
    if forced.lower() == "none":
        return None
    if forced:
        return forced if shutil.which(forced, path=env.get("PATH")) else None
    for name in CLI_COMMANDS:
        if shutil.which(name, path=env.get("PATH")):
            return name
    return None


def cli_argv(name: str, prompt: str) -> list[str]:
    template = CLI_COMMANDS.get(name) or (name, "-p", "{prompt}")
    return [prompt if part == "{prompt}" else part for part in template]


_SHIM_TARGET = re.compile(r'"%(?:~dp0|dp0%)\\([^"]+)"\s+%\*')
_SHIM_INTERPRETERS = {".js": "node", ".cjs": "node", ".mjs": "node", ".py": sys.executable}


def resolve_cli(exe: str) -> list[str]:
    """argv prefix that runs `exe` without a shell. On Windows, npm installs CLIs as `<name>.cmd` batch shims
    (`node "%dp0%\\...\\cli.js" %*`); running those through cmd.exe mangles quotes/newlines in the prompt, so
    the shim is bypassed and its target is run with the interpreter directly."""
    if not exe.lower().endswith((".cmd", ".bat")):
        return [exe]
    try:
        with open(exe, encoding="utf-8", errors="replace") as fh:
            m = _SHIM_TARGET.search(fh.read())
    except OSError:
        m = None
    if m is None:
        return [exe]
    target = os.path.join(os.path.dirname(exe), m.group(1).replace("\\", os.sep))
    interp = _SHIM_INTERPRETERS.get(os.path.splitext(target)[1].lower())
    if interp is None or not os.path.exists(target):
        return [exe]
    interp_path = interp if os.path.isabs(interp) else shutil.which(interp)
    return [interp_path, target] if interp_path else [exe]


def build_prompt(messages: list[dict[str, str]], response_schema: dict[str, Any] | None = None) -> str:
    """System + user (+ any other) messages joined in order, blank-line separated; JSON-only instruction appended when a schema is given."""
    parts = [str(m.get("content", "")) for m in messages if str(m.get("content", "")).strip()]
    if response_schema is not None:
        parts.append(JSON_INSTRUCTION + json.dumps(response_schema, separators=(",", ":")))
    return "\n\n".join(parts)


def first_json_object(text: str) -> dict[str, Any] | None:
    """The first JSON object in free text (agent CLIs wrap replies in prose or ``` fences)."""
    dec = json.JSONDecoder()
    i = text.find("{")
    while i != -1:
        try:
            obj, _ = dec.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict):
            return obj
        i = text.find("{", i + 1)
    return None


def describe_access(state: dict[str, Any] | None = None) -> str:
    """One line for `./interview status`: "gateway" / "<name> CLI" / "none — rules only". Never prints URLs or tokens."""
    st = _interview_state() if state is None else state
    provider = (os.environ.get("MODEL_PROVIDER") or "auto").lower()
    cli = find_cli()
    gateway_on = bool(os.environ.get("MODEL_BASE_URL") or (st.get("gateway_url") and st.get("models") == "ON"))
    if provider != "cli" and gateway_on:
        return "gateway" + (f" (+ {cli} CLI fallback)" if cli else "")
    if provider != "gateway" and cli:
        return f"{cli} CLI"
    return "none — rules only"


class ModelClient:
    def __init__(self, base_url: str | None = None, attempt_token: str | None = None, timeout: float = 20.0,
                 provider: str | None = None, cli_timeout: float = CLI_TIMEOUT_S) -> None:
        st = _interview_state()
        configured = base_url or os.environ.get("MODEL_BASE_URL") or st.get("gateway_url")
        self.gateway_configured = bool(configured)
        self.base_url = (configured or "http://localhost:8081").rstrip("/")
        self.attempt_token = attempt_token or os.environ.get("ATTEMPT_TOKEN") or st.get("attempt_token") or "local-dev"
        self.timeout = timeout
        self.cli_timeout = cli_timeout
        self.provider = (provider or os.environ.get("MODEL_PROVIDER") or "auto").lower()
        if self.provider not in ("auto", "gateway", "cli"):
            raise ModelRequestError(f"MODEL_PROVIDER must be auto|gateway|cli, not {self.provider!r}")
        self.last_provider: str | None = None

    def complete(self, *, model: str, messages: list[dict[str, str]], response_schema: dict[str, Any] | None = None,
                 temperature: float = 0.0) -> ModelResponse:
        if model not in MODELS:
            raise ModelRequestError(f"unknown model {model!r}; use one of {MODELS}")
        if self.provider == "cli" or (self.provider == "auto" and not self.gateway_configured):
            return self._complete_cli(model, messages, response_schema)
        try:
            return self._complete_gateway(model, messages, response_schema, temperature)
        except ModelUnavailable as exc:
            if self.provider == "gateway" or exc.outage or find_cli() is None:
                raise
            return self._complete_cli(model, messages, response_schema)

    def _complete_gateway(self, model: str, messages: list[dict[str, str]], response_schema: dict[str, Any] | None,
                          temperature: float) -> ModelResponse:
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
                raise ModelUnavailable("gateway outage", outage=True) from exc
            detail = exc.read().decode(errors="replace")
            raise ModelRequestError(f"gateway {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise ModelUnavailable(f"gateway unreachable: {exc}") from exc
        self.last_provider = "gateway"
        return ModelResponse(content=data["content"], model=data["model"], usage=data.get("usage", {}),
                             latency_ms=int(data.get("latency_ms", (time.time() - t0) * 1000)),
                             request_id=data.get("request_id", ""))

    def _complete_cli(self, model: str, messages: list[dict[str, str]], response_schema: dict[str, Any] | None) -> ModelResponse:
        name = find_cli()
        if name is None:
            raise ModelUnavailable("no model access: gateway not reachable and no agent CLI (claude/codex/cursor-agent/gemini) on PATH")
        argv = cli_argv(name, build_prompt(messages, response_schema))
        argv = resolve_cli(shutil.which(name) or name) + argv[1:]
        t0 = time.time()
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=self.cli_timeout, stdin=subprocess.DEVNULL, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ModelUnavailable(f"{name} CLI timed out after {self.cli_timeout:.0f} s") from exc
        except OSError as exc:
            raise ModelUnavailable(f"{name} CLI could not start: {exc}") from exc
        if r.returncode != 0:
            raise ModelUnavailable(f"{name} CLI exited {r.returncode}: {r.stderr.strip()[-500:]}")
        text = r.stdout.strip()
        content: str | dict[str, Any] = text
        if response_schema is not None:
            obj = first_json_object(text)
            if obj is None:
                raise ModelUnavailable(f"{name} CLI reply contained no JSON object")
            content = obj
        self.last_provider = f"cli:{name}"
        return ModelResponse(content=content, model=f"{name}:{model}", usage={}, latency_ms=int((time.time() - t0) * 1000), request_id="")

    def set_outage(self, down: bool) -> None:
        """Harness-only: mirror a fixture `system.model_outage` event onto the gateway. Candidates never call this."""
        body = json.dumps({"attempt_token": self.attempt_token, "down": down}).encode()
        req = urllib.request.Request(f"{self.base_url}/v1/admin/force_outage", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=self.timeout).read()
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass

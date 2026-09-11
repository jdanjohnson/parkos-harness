"""Drive a handler over a fixture. Shared by public tests, replay, and the evaluator."""
from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from typing import Any

from scaffold.context import Context
from scaffold.decisions import Decision
from scaffold.events import Event, read_jsonl

Builder = Callable[[Context], Any]


def load_builder(dotted: str = "candidate.main:build") -> Builder:
    mod, _, attr = dotted.partition(":")
    return getattr(importlib.import_module(mod), attr or "build")


def run_fixture(path: str, builder: Builder, model: Any = None, quiet: bool = True,
                on_event: Callable[[Event], None] | None = None) -> dict[str, Any]:
    ctx = Context.fresh(model=model, quiet=quiet)
    handler = builder(ctx)
    decisions: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for ev in read_jsonl(path):
        ctx.clock.observe(ev)
        ctx.tools.observe(ev)
        if on_event:
            on_event(ev)
        if ev.type == "system.model_outage" and model is not None and hasattr(model, "set_outage"):
            model.set_outage(ev.payload.get("state") == "down")
        try:
            d = handler.handle(ev)
            if not isinstance(d, Decision):
                raise TypeError(f"handle() must return Decision, got {type(d).__name__}")
            decisions.append(d.to_dict())
        except Exception as exc:  # noqa: BLE001 - candidate code; record and continue
            errors.append({"event_id": ev.id, "error": f"{type(exc).__name__}: {exc}"})
            decisions.append(Decision.noop(ev.id, "invalid_event").to_dict())
    return {"fixture": path, "decisions": decisions, "errors": errors, "ledger": ctx.ledger.snapshot(),
            "history": [e.__dict__ for e in ctx.ledger.history()], "tool_calls": ctx.tools.calls(),
            "approvals": {k: {**v, "requested_at": v["requested_at"].isoformat(),
                              "answered_at": v["answered_at"].isoformat() if v["answered_at"] else None}
                          for k, v in ctx.tools.approvals().items()},
            "logs": ctx.logs}


if __name__ == "__main__":
    import sys
    res = run_fixture(sys.argv[1], load_builder(sys.argv[2] if len(sys.argv) > 2 else "candidate.main:build"))
    print(json.dumps(res, indent=2, default=str))

"""Run context handed to candidate handlers. See CONTRACTS.md §4."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .events import Event
from .ledger import Ledger
from .tools import Tools


class Clock:
    """Fixture-driven clock. Advances monotonically with event timestamps and system.tick."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 9, 10, 6, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def observe(self, event: Event) -> None:
        self._now = max(self._now, event.ts)

    def advance(self, seconds: int) -> None:
        self._now = self._now + timedelta(seconds=seconds)


@dataclass
class Context:
    ledger: Ledger
    tools: Tools
    clock: Clock
    model: Any = None                     # ModelClient or None in Phase 2 runs
    log: Callable[[str], None] = print
    logs: list[str] = field(default_factory=list)

    @classmethod
    def fresh(cls, model: Any = None, quiet: bool = True) -> Context:
        ledger = Ledger()
        clock = Clock()
        ctx = cls(ledger=ledger, tools=None, clock=clock, model=model)  # type: ignore[arg-type]
        ctx.tools = Tools(ledger, clock)

        def _log(msg: str) -> None:
            ctx.logs.append(msg)
            if not quiet:
                print(msg)

        ctx.log = _log
        return ctx

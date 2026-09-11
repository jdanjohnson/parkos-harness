"""Phase 2 — you own this file. See problem/TASK.md (unpacked at Phase 2) and CONTRACTS §5."""
from __future__ import annotations

from scaffold.context import Context
from scaffold.decisions import Decision
from scaffold.events import Event


class StructuredReconciler:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx

    def handle(self, event: Event) -> Decision:
        raise NotImplementedError("implement StructuredReconciler.handle")

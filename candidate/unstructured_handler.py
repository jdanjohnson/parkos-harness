"""Phase 3 — you own this file. See problem/TASK.md and CONTRACTS §5/§6."""
from __future__ import annotations

from scaffold.context import Context
from scaffold.decisions import Decision
from scaffold.events import Event

from .structured_reconciler import StructuredReconciler


class UnstructuredHandler:
    def __init__(self, ctx: Context, structured: StructuredReconciler) -> None:
        self.ctx = ctx
        self.structured = structured

    def handle(self, event: Event) -> Decision:
        raise NotImplementedError("implement UnstructuredHandler.handle")

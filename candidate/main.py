"""Entry point the harness calls: build(ctx).handle(event). Edit freely, keep the signature."""
from __future__ import annotations

from scaffold.context import Context
from scaffold.decisions import Decision
from scaffold.events import Event

from .structured_reconciler import StructuredReconciler
from .unstructured_handler import UnstructuredHandler


class Router:
    def __init__(self, ctx: Context) -> None:
        self.structured = StructuredReconciler(ctx)
        self.unstructured = UnstructuredHandler(ctx, self.structured)

    def handle(self, event: Event) -> Decision:
        if event.is_unstructured:
            return self.unstructured.handle(event)
        return self.structured.handle(event)


def build(ctx: Context) -> Router:
    return Router(ctx)

"""Decision record. See CONTRACTS.md §2. A Decision reports what the handler did; it does not request it."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ACTION_TYPES = frozenset({
    "assign_spot", "release_spot", "record_payment", "mark_conflict", "resolve_conflict",
    "escalate", "request_approval", "record_refund", "void_charge", "noop", "defer",
})


class Flag:
    CONFLICT = "conflict"
    UNTRUSTED_TEXT = "untrusted_text"
    NEEDS_APPROVAL = "needs_approval"
    UPSTREAM_ISSUE = "upstream_issue"
    DUPLICATE = "duplicate"
    INVALID_EVENT = "invalid_event"
    DEFERRED = "deferred"
    LOW_CONFIDENCE = "low_confidence"
    ALL = frozenset({CONFLICT, UNTRUSTED_TEXT, NEEDS_APPROVAL, UPSTREAM_ISSUE,
                     DUPLICATE, INVALID_EVENT, DEFERRED, LOW_CONFIDENCE})


@dataclass
class Action:
    type: str
    args: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in ACTION_TYPES:
            raise ValueError(f"unknown action type {self.type!r}")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type}
        d.update(self.args)
        return d


@dataclass
class Decision:
    event_id: str
    actions: list[Action] = field(default_factory=list)
    escalated: bool = False
    evidence: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    confidence: float | None = None

    def add(self, action_type: str, **args: Any) -> Decision:
        self.actions.append(Action(action_type, args))
        return self

    def flag(self, *flags: str) -> Decision:
        for f in flags:
            if f not in Flag.ALL:
                raise ValueError(f"unknown flag {f!r}")
            if f not in self.flags:
                self.flags.append(f)
        return self

    def to_dict(self) -> dict[str, Any]:
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0,1]")
        return {
            "event_id": self.event_id,
            "actions": [a.to_dict() for a in self.actions],
            "escalated": bool(self.escalated),
            "evidence": list(self.evidence),
            "flags": list(self.flags),
            "confidence": self.confidence,
        }

    @staticmethod
    def noop(event_id: str, *flags: str, evidence: list[str] | None = None) -> Decision:
        d = Decision(event_id=event_id, evidence=list(evidence or [event_id]))
        d.add("noop")
        if flags:
            d.flag(*flags)
        return d

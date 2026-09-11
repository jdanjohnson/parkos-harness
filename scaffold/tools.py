"""Runtime tools. See CONTRACTS.md §4. Tools expose information and side-channel actions;
they never mutate the ledger."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from .events import Event
from .ledger import Ledger

APPROVAL_TIMEOUT = timedelta(minutes=15)
APPROVAL_KINDS = ("refund", "void", "comp")
PACKET_REQUIRED_KEYS = ("what", "why_it_matters", "evidence", "options", "default_if_no_answer")


class Tools:
    def __init__(self, ledger: Ledger, clock: Any) -> None:
        self._ledger = ledger
        self._clock = clock
        self._reservations: dict[str, dict[str, Any]] = {}
        self._cancelled: set = set()
        self._payments: list[dict[str, Any]] = []
        self._approvals: dict[str, dict[str, Any]] = {}
        self._calls: list[dict[str, Any]] = []
        self._counter = 0

    # ---- harness feeds app events in so lookups reflect "what the app knows" ----
    def observe(self, event: Event) -> None:
        p = event.payload
        if event.type == "app.reservation" and "reservation_id" in p:
            self._reservations[p["reservation_id"]] = dict(p, event_id=event.id)
        elif event.type == "app.cancel" and "reservation_id" in p:
            self._cancelled.add(p["reservation_id"])
        elif event.type == "app.payment" and "payment_ref" in p:
            self._payments.append(dict(p, event_id=event.id))
        elif event.type == "manager.approval":
            ref = p.get("approval_ref")
            if ref in self._approvals and self._approvals[ref]["status"] == "pending":
                self._approvals[ref]["status"] = "approved" if p.get("decision") == "approve" else "denied"
                self._approvals[ref]["answered_at"] = self._clock.now()

    def _record(self, name: str, **kw: Any) -> str:
        self._counter += 1
        call_id = f"tool_{self._counter:04d}"
        self._calls.append({"id": call_id, "tool": name, "at": self._clock.now().isoformat(), **kw})
        return call_id

    # ---- lookups ------------------------------------------------------------
    def lookup_reservation(self, *, reservation_id: str | None = None, plate: str | None = None,
                           spot: str | None = None) -> list[dict[str, Any]]:
        self._record("lookup_reservation", reservation_id=reservation_id, plate=plate, spot=spot)
        out = []
        for rid, r in self._reservations.items():
            if rid in self._cancelled:
                continue
            if reservation_id and rid != reservation_id:
                continue
            if plate and r.get("plate") != plate:
                continue
            if spot and r.get("spot") != spot:
                continue
            out.append(dict(r))
        return out

    def lookup_payment(self, *, payment_ref: str | None = None, plate: str | None = None) -> list[dict[str, Any]]:
        self._record("lookup_payment", payment_ref=payment_ref, plate=plate)
        return [dict(p) for p in self._payments
                if (payment_ref is None or p.get("payment_ref") == payment_ref)
                and (plate is None or p.get("plate") == plate)]

    def lookup_plate(self, plate: str) -> dict[str, Any]:
        self._record("lookup_plate", plate=plate)
        return {
            "plate": plate,
            "spots": self._ledger.get_vehicle(plate).spots,
            "reservations": [dict(r) for rid, r in self._reservations.items()
                             if r.get("plate") == plate and rid not in self._cancelled],
            "payments": [dict(p) for p in self._payments if p.get("plate") == plate],
        }

    # ---- side channels ------------------------------------------------------
    def ask_attendant(self, question: str, *, evidence: list[str]) -> str:
        if not isinstance(evidence, list):
            raise TypeError("evidence must be a list")
        return self._record("ask_attendant", question=question, evidence=list(evidence))

    def escalate(self, packet: dict[str, Any], *, evidence: list[str]) -> str:
        if not isinstance(packet, dict):
            raise TypeError("packet must be a dict")
        if not isinstance(evidence, list):
            raise TypeError("evidence must be a list")
        missing = [k for k in PACKET_REQUIRED_KEYS if k not in packet]
        return self._record("escalate", packet=dict(packet), evidence=list(evidence), missing_keys=missing)

    def request_approval(self, *, kind: str, amount: int, ref: str, evidence: list[str], reason: str) -> str:
        if kind not in APPROVAL_KINDS:
            raise ValueError(f"kind must be one of {APPROVAL_KINDS}")
        if not isinstance(amount, int) or amount < 0:
            raise ValueError("amount must be non-negative int cents")
        if not isinstance(evidence, list):
            raise TypeError("evidence must be a list")
        if ref not in self._approvals:
            self._approvals[ref] = {"kind": kind, "amount": amount, "reason": reason, "evidence": list(evidence),
                                    "status": "pending", "requested_at": self._clock.now(), "answered_at": None}
        self._record("request_approval", kind=kind, amount=amount, ref=ref, reason=reason, evidence=list(evidence))
        return ref

    def approval_status(self, approval_ref: str) -> str:
        a = self._approvals.get(approval_ref)
        if a is None:
            return "unknown"
        if a["status"] == "pending" and self._clock.now() - a["requested_at"] >= APPROVAL_TIMEOUT:
            a["status"] = "expired"
        return a["status"]

    def approvals(self) -> dict[str, dict[str, Any]]:
        for ref in list(self._approvals):
            self.approval_status(ref)
        return {k: dict(v) for k, v in self._approvals.items()}

    def calls(self) -> list[dict[str, Any]]:
        return [dict(c) for c in self._calls]

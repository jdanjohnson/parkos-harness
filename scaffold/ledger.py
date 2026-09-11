"""The ledger. See CONTRACTS.md §3.

Dumb on purpose: it records exactly what it is told and never enforces invariants.
Deciding whether a call is legal is the reconciler's job. The evaluator reads history()
to see whether that job was done.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SpotState:
    spot: str
    plate: str | None
    reservation_id: str | None
    since: str | None      # ISO ts of assigning event (taken from evidence if provided as 'since'), else wall time
    conflict: bool

    @property
    def occupied(self) -> bool:
        return self.plate is not None


@dataclass(frozen=True)
class VehicleState:
    plate: str
    spots: list[str]


@dataclass(frozen=True)
class PaymentRecord:
    payment_ref: str
    plate: str
    amount: int
    evidence: list[str]


@dataclass(frozen=True)
class RefundRecord:
    payment_ref: str
    amount: int
    approval_ref: str | None
    evidence: list[str]


@dataclass(frozen=True)
class LedgerEntry:
    seq: int
    op: str
    args: dict[str, Any]
    evidence: list[str]
    prev: dict[str, Any] | None
    ts_wall: float


class Ledger:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._spots: dict[str, dict[str, Any]] = {}
        self._payments: list[PaymentRecord] = []
        self._refunds: list[RefundRecord] = []
        self._voids: list[dict[str, Any]] = []
        self._conflicts: dict[str, dict[str, Any]] = {}
        self._history: list[LedgerEntry] = []

    # ---- internal ------------------------------------------------------
    def _log(self, op: str, args: dict[str, Any], evidence: list[str], prev: dict[str, Any] | None) -> None:
        self._history.append(LedgerEntry(len(self._history) + 1, op, dict(args), list(evidence), prev, time.time()))

    @staticmethod
    def _ev(evidence: Any) -> list[str]:
        if evidence is None:
            raise TypeError("evidence is required (list of event/tool ids)")
        if isinstance(evidence, str):
            raise TypeError("evidence must be a list of ids, not a string")
        return [str(e) for e in evidence]

    # ---- reads ---------------------------------------------------------
    def get_spot(self, spot: str) -> SpotState:
        with self._lock:
            s = self._spots.get(spot)
            conflict = spot in self._conflicts
            if not s:
                return SpotState(spot, None, None, None, conflict)
            return SpotState(spot, s["plate"], s.get("reservation_id"), s.get("since"), conflict)

    def get_vehicle(self, plate: str) -> VehicleState:
        with self._lock:
            return VehicleState(plate, sorted(k for k, v in self._spots.items() if v["plate"] == plate))

    def payments(self, plate: str | None = None) -> list[PaymentRecord]:
        with self._lock:
            return [p for p in self._payments if plate is None or p.plate == plate]

    def refunds(self, payment_ref: str | None = None) -> list[RefundRecord]:
        with self._lock:
            return [r for r in self._refunds if payment_ref is None or r.payment_ref == payment_ref]

    def conflicts(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._conflicts.items()}

    def history(self) -> list[LedgerEntry]:
        with self._lock:
            return list(self._history)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            vehicles: dict[str, list[str]] = {}
            for spot, s in self._spots.items():
                vehicles.setdefault(s["plate"], []).append(spot)
            return {
                "spots": {k: dict(v) for k, v in sorted(self._spots.items())},
                "vehicles": {k: sorted(v) for k, v in sorted(vehicles.items())},
                "payments": [p.__dict__ for p in self._payments],
                "refunds": [r.__dict__ for r in self._refunds],
                "voids": list(self._voids),
                "conflicts": {k: dict(v) for k, v in self._conflicts.items()},
            }

    # ---- writes (no validation, by design) -----------------------------
    def assign_spot(self, spot: str, plate: str, *, evidence: list[str],
                    reservation_id: str | None = None, since: str | None = None) -> None:
        ev = self._ev(evidence)
        with self._lock:
            prev = dict(self._spots[spot]) if spot in self._spots else None
            self._spots[spot] = {"plate": plate, "reservation_id": reservation_id,
                                 "since": since or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            self._log("assign", {"spot": spot, "plate": plate, "reservation_id": reservation_id}, ev, prev)

    def release_spot(self, spot: str, *, evidence: list[str]) -> None:
        ev = self._ev(evidence)
        with self._lock:
            prev = self._spots.pop(spot, None)
            self._log("release", {"spot": spot}, ev, dict(prev) if prev else None)

    def record_payment(self, payment_ref: str, plate: str, amount: int, *, evidence: list[str]) -> None:
        ev = self._ev(evidence)
        if not isinstance(amount, int):
            raise TypeError("amount must be int cents")
        with self._lock:
            prev_count = sum(1 for p in self._payments if p.payment_ref == payment_ref)
            self._payments.append(PaymentRecord(payment_ref, plate, amount, ev))
            self._log("payment", {"payment_ref": payment_ref, "plate": plate, "amount": amount}, ev,
                      {"prior_records_with_ref": prev_count} if prev_count else None)

    def record_refund(self, payment_ref: str, amount: int, *, approval_ref: str | None,
                      evidence: list[str]) -> None:
        ev = self._ev(evidence)
        if not isinstance(amount, int):
            raise TypeError("amount must be int cents")
        with self._lock:
            self._refunds.append(RefundRecord(payment_ref, amount, approval_ref, ev))
            self._log("refund", {"payment_ref": payment_ref, "amount": amount, "approval_ref": approval_ref}, ev, None)

    def void_charge(self, payment_ref: str, *, approval_ref: str | None, evidence: list[str]) -> None:
        ev = self._ev(evidence)
        with self._lock:
            self._voids.append({"payment_ref": payment_ref, "approval_ref": approval_ref, "evidence": ev})
            self._log("void", {"payment_ref": payment_ref, "approval_ref": approval_ref}, ev, None)

    def mark_conflict(self, spot: str, description: str, *, evidence: list[str]) -> None:
        ev = self._ev(evidence)
        with self._lock:
            prev = dict(self._conflicts[spot]) if spot in self._conflicts else None
            self._conflicts[spot] = {"description": description, "evidence": ev}
            self._log("mark_conflict", {"spot": spot, "description": description}, ev, prev)

    def resolve_conflict(self, spot: str, *, evidence: list[str]) -> None:
        ev = self._ev(evidence)
        with self._lock:
            prev = self._conflicts.pop(spot, None)
            self._log("resolve_conflict", {"spot": spot}, ev, prev)

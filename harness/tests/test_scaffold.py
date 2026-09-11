"""Scaffold self-tests. These run in ./check and prove the harness primitives behave as CONTRACTS.md says."""
import pytest

from scaffold.context import Context
from scaffold.decisions import Action, Decision, Flag
from scaffold.events import Event
from scaffold.ledger import Ledger


def test_event_parse_and_roundtrip():
    e = Event.from_dict({"id": "e1", "type": "app.checkin", "ts": "2026-09-10T12:30:00Z", "source": "app",
                         "payload": {"spot": "A4", "plate": "ABC123"}})
    assert e.is_structured and not e.is_unstructured
    assert e.ts.hour == 12 and e.ts.tzinfo is not None
    assert e.to_dict()["ts"] == "2026-09-10T12:30:00Z"
    assert Event.from_dict({"id": "b", "type": "booth.entry", "ts": "2026-09-10T12:00:00+02:00", "source": "booth"}).ts.hour == 10


def test_event_rejects_missing_fields_and_bad_payload():
    with pytest.raises(ValueError, match="missing 'ts'"):
        Event.from_dict({"id": "e", "type": "x", "source": "app"})
    with pytest.raises(ValueError, match="payload must be an object"):
        Event.from_dict({"id": "e", "type": "x", "ts": "2026-01-01T00:00:00Z", "source": "app", "payload": []})


def test_ledger_is_dumb_but_remembers_prev():
    led = Ledger()
    led.assign_spot("A1", "ABC123", evidence=["e1"])
    led.assign_spot("A1", "XYZ789", evidence=["e2"])          # silent overwrite is allowed...
    assert led.get_spot("A1").plate == "XYZ789"
    h = led.history()
    assert [x.op for x in h] == ["assign", "assign"]
    assert h[0].prev is None
    assert h[1].prev["plate"] == "ABC123"                       # ...but visible to the scorer
    led.assign_spot("A2", "XYZ789", evidence=["e3"])
    assert led.get_vehicle("XYZ789").spots == ["A1", "A2"]     # vehicle invariant not enforced
    led.record_payment("p1", "XYZ789", 1800, evidence=["e4"])
    led.record_payment("p1", "XYZ789", 1800, evidence=["e5"])
    assert len(led.payments("XYZ789")) == 2
    assert led.history()[-1].prev == {"prior_records_with_ref": 1}


def test_ledger_requires_list_evidence_and_int_amount():
    led = Ledger()
    with pytest.raises(TypeError):
        led.assign_spot("A1", "ABC123", evidence="e1")
    with pytest.raises(TypeError):
        led.record_payment("p", "ABC123", 18.0, evidence=["e"])
    assert led.history() == []


def test_ledger_release_and_conflict_flow():
    led = Ledger()
    led.mark_conflict("A1", "two claims", evidence=["e1", "e2"])
    assert led.get_spot("A1").conflict is True
    led.resolve_conflict("A1", evidence=["e3"])
    assert led.get_spot("A1").conflict is False and led.history()[-1].prev["description"] == "two claims"
    led.release_spot("A9", evidence=["e4"])                    # releasing empty spot logs, doesn't raise
    assert led.history()[-1].prev is None
    snap = led.snapshot()
    assert snap["spots"] == {} and snap["conflicts"] == {}


def test_decision_serialisation_and_validation():
    d = Decision(event_id="e1").add("assign_spot", spot="A1", plate="ABC123").flag(Flag.CONFLICT)
    assert d.to_dict() == {"event_id": "e1", "actions": [{"type": "assign_spot", "spot": "A1", "plate": "ABC123"}],
                           "escalated": False, "evidence": [], "flags": ["conflict"], "confidence": None}
    with pytest.raises(ValueError):
        Action("refund_everyone")
    with pytest.raises(ValueError):
        d.flag("made_up")
    d.confidence = 1.5
    with pytest.raises(ValueError):
        d.to_dict()


def test_tools_reflect_app_knowledge_and_approval_timeout():
    ctx = Context.fresh()
    res = Event.from_dict({"id": "r1", "type": "app.reservation", "ts": "2026-09-10T08:00:00Z", "source": "app",
                           "payload": {"reservation_id": "res_1", "spot": "A1", "plate": "ABC123", "start": "", "end": "", "amount": 1800}})
    ctx.clock.observe(res); ctx.tools.observe(res)
    assert ctx.tools.lookup_reservation(plate="ABC123")[0]["reservation_id"] == "res_1"
    can = Event.from_dict({"id": "c1", "type": "app.cancel", "ts": "2026-09-10T08:05:00Z", "source": "app", "payload": {"reservation_id": "res_1"}})
    ctx.tools.observe(can)
    assert ctx.tools.lookup_reservation(plate="ABC123") == []
    ref = ctx.tools.request_approval(kind="refund", amount=1800, ref="apr_1", evidence=["r1"], reason="dup")
    assert ref == "apr_1" and ctx.tools.approval_status("apr_1") == "pending"
    ctx.clock.advance(15 * 60)
    assert ctx.tools.approval_status("apr_1") == "expired"
    ref2 = ctx.tools.request_approval(kind="void", amount=100, ref="apr_2", evidence=[], reason="x")
    ok = Event.from_dict({"id": "m1", "type": "manager.approval", "ts": "2026-09-10T08:30:00Z", "source": "manager",
                          "payload": {"approval_ref": "apr_2", "decision": "approve"}})
    ctx.clock.observe(ok); ctx.tools.observe(ok)
    assert ctx.tools.approval_status(ref2) == "approved"
    with pytest.raises(ValueError):
        ctx.tools.request_approval(kind="gift", amount=1, ref="x", evidence=[], reason="")
    assert ctx.tools.escalate({"what": "x"}, evidence=["r1"]).startswith("tool_")
    assert ctx.tools.calls()[-1]["missing_keys"] == ["why_it_matters", "evidence", "options", "default_if_no_answer"]

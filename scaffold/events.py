"""Event model. See CONTRACTS.md §1."""
from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

STRUCTURED_PREFIXES = ("app.", "manager.", "system.")
UNSTRUCTURED_PREFIXES = ("booth.", "driver.")

STANDARD_SPOTS = [f"A{i}" for i in range(1, 17)]
EV_SPOTS = ["E1", "E2"]
ACCESSIBLE_SPOTS = ["H1", "H2"]
ALL_SPOTS = STANDARD_SPOTS + EV_SPOTS + ACCESSIBLE_SPOTS


def parse_ts(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Event:
    id: str
    type: str
    ts: datetime
    source: str
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def is_structured(self) -> bool:
        return self.type.startswith(STRUCTURED_PREFIXES)

    @property
    def is_unstructured(self) -> bool:
        return self.type.startswith(UNSTRUCTURED_PREFIXES)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Event:
        for key in ("id", "type", "ts", "source"):
            if key not in d:
                raise ValueError(f"event missing '{key}': {d!r}")
        payload = d.get("payload", {})
        if not isinstance(payload, dict):
            raise ValueError(f"event {d['id']} payload must be an object")  # noqa: TRY004
        return cls(id=str(d["id"]), type=str(d["type"]), ts=parse_ts(str(d["ts"])),
                   source=str(d["source"]), payload=dict(payload))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type,
                "ts": self.ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": self.source, "payload": dict(self.payload)}


def read_jsonl(path: str) -> list[Event]:
    return list(iter_jsonl(path))


def iter_jsonl(path: str) -> Iterator[Event]:
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                yield Event.from_dict(json.loads(line))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"{path}:{lineno}: {exc}") from exc

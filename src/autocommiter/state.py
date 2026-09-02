from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, TypeVar

from .config import app_data_dir

T = TypeVar("T")


def state_path() -> Path:
    return app_data_dir() / "state.json"


@dataclass(slots=True)
class DailyState:
    day: str
    detected_changes_today: int = 0
    committed_changes_today: int = 0
    last_status: str = "Nao iniciado"
    last_fingerprint: dict[str, object] | None = None

    @classmethod
    def for_today(cls, today: date) -> DailyState:
        return cls(day=today.isoformat())

    def to_json(self) -> str:
        payload = asdict(self)
        if self.last_fingerprint is not None:
            payload["last_fingerprint"] = self.last_fingerprint
        return json.dumps(payload, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> DailyState:
        data = json.loads(raw)
        return cls(
            day=str(data["day"]),
            detected_changes_today=int(data.get("detected_changes_today", 0)),
            committed_changes_today=int(data.get("committed_changes_today", 0)),
            last_status=str(data.get("last_status", "Nao iniciado")),
            last_fingerprint=(
                data.get("last_fingerprint")
                if isinstance(data.get("last_fingerprint"), dict)
                else None
            ),
        )


class DailyStateStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or state_path()

    def load(self, today: date | None = None) -> DailyState:
        current_day = today or date.today()
        if not self.path.exists():
            return DailyState.for_today(current_day)
        raw = self.path.read_text(encoding="utf-8")
        state = DailyState.from_json(raw)
        if state.day != current_day.isoformat():
            return DailyState.for_today(current_day)
        return state

    def save(self, state: DailyState) -> DailyState:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(state.to_json(), encoding="utf-8")
        tmp.replace(self.path)
        return state

    def restore_fingerprint(self, fingerprint_cls: type[T]) -> T | None:
        state = self.load()
        if state.last_fingerprint is None:
            return None
        data = state.last_fingerprint
        return fingerprint_cls(  # type: ignore[call-arg]
            exists=bool(data.get("exists", False)),
            size=int(data.get("size", 0)),  # type: ignore[call-overload]
            mtime_ns=int(data.get("mtime_ns", 0)),  # type: ignore[call-overload]
            sha256=str(data.get("sha256", "")),
        )

    def persist_fingerprint(self, fingerprint: Any, fingerprint_cls: type[Any]) -> None:
        state = self.load()
        state.last_fingerprint = {
            "exists": bool(fingerprint.exists),
            "size": int(fingerprint.size),
            "mtime_ns": int(fingerprint.mtime_ns),
            "sha256": str(fingerprint.sha256),
        }
        self.save(state)

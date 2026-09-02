from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from .config import AppConfig
from .git_ops import commit, ensure_repository, has_staged_changes, push, stage_paths
from .state import DailyState, DailyStateStore

TEMPLATE_NAME = "daily.md"


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        ...

    @abstractmethod
    def today(self) -> date:
        ...


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return date.today()

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    exists: bool
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PollResult:
    detected_change: bool
    created_commit: bool
    status: str
    limit_reached: bool = False


def fingerprint(path: Path) -> FileFingerprint:
    if not path.exists():
        return FileFingerprint(exists=False, size=0, mtime_ns=0, sha256="")

    contents = path.read_bytes()
    stat = path.stat()
    return FileFingerprint(
        exists=True,
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        sha256=hashlib.sha256(contents).hexdigest(),
    )


class WatcherService:
    def __init__(
        self,
        config: AppConfig,
        state_store: DailyStateStore | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.config = config
        self.state_store = state_store or DailyStateStore()
        self.clock = clock or SystemClock()
        self._last_fingerprint: FileFingerprint | None = (
            self.state_store.restore_fingerprint(FileFingerprint)
        )
        self._pending_fingerprint: FileFingerprint | None = None
        self._pending_since: datetime | None = None

    @property
    def mirrored_file_path(self) -> Path:
        return self.config.repository_path / self.config.tracked_relative_path

    @property
    def active_watched_file(self) -> Path:
        if self.config.daily_notes_directory is None:
            return self.config.watched_file
        return self.resolve_today_note()

    @property
    def metadata_path(self) -> Path:
        return self.config.repository_path / ".autocommiter" / "last-event.json"

    def initialize(self) -> None:
        ensure_repository(self.config.repository_path)
        if self.mirrored_file_path.exists():
            self._last_fingerprint = fingerprint(self.mirrored_file_path)
            self.state_store.persist_fingerprint(self._last_fingerprint, FileFingerprint)
            self._write_status("Pronto para monitorar")
            return
        current_file = self.active_watched_file
        self._last_fingerprint = fingerprint(current_file)
        self.state_store.persist_fingerprint(self._last_fingerprint, FileFingerprint)
        if current_file.exists():
            self._write_status("Pronto para monitorar")
            return
        if self.config.daily_notes_directory is not None and not current_file.exists():
            self._create_today_note_from_template(current_file)
            if current_file.exists():
                self._write_status("Pronto para monitorar (nota criada)")
                return
        self._write_status("Arquivo monitorado nao encontrado")

    def _create_today_note_from_template(self, target: Path) -> None:
        template_path = Path(__file__).resolve().parent / "templates" / TEMPLATE_NAME
        if not template_path.exists():
            LOGGER.warning("Template %s nao encontrado em %s", TEMPLATE_NAME, template_path)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        today_str = self.clock.now().strftime("%d-%m-%Y")
        content = template_path.read_text(encoding="utf-8").replace("{{DATE}}", today_str)
        target.write_text(content, encoding="utf-8")
        LOGGER.info("Nota do dia criada a partir do template: %s", target)
        self._last_fingerprint = fingerprint(target)
        self.state_store.persist_fingerprint(self._last_fingerprint, FileFingerprint)

    def run_forever(self) -> None:
        self.initialize()
        LOGGER.info("Monitoring %s", self.active_watched_file)
        while True:
            try:
                self.poll_once()
            except Exception:
                LOGGER.exception("Watcher iteration failed")
                self._write_status("Falha durante o monitoramento")
            time.sleep(self.config.poll_interval_seconds)

    def poll_once(self) -> PollResult:
        state = self.state_store.load(today=self.clock.today())
        if state.detected_changes_today >= self.config.max_detections_per_day:
            result = PollResult(
                detected_change=False,
                created_commit=False,
                status="Limite diario de deteccoes atingido",
                limit_reached=True,
            )
            self._write_status(result.status, state)
            return result

        current = fingerprint(self.active_watched_file)
        if self._last_fingerprint is None:
            self._last_fingerprint = current
            state.last_fingerprint = {
                "exists": current.exists,
                "size": current.size,
                "mtime_ns": current.mtime_ns,
                "sha256": current.sha256,
            }
            result = PollResult(False, False, "Monitoramento inicializado")
            self._write_status(result.status, state)
            return result
        if current == self._last_fingerprint:
            # Reset debounce pending when file stabilizes to known state
            self._pending_fingerprint = None
            self._pending_since = None
            status = "Aguardando mudancas no arquivo"
            if not current.exists:
                status = "Arquivo monitorado nao encontrado"
            result = PollResult(False, False, status)
            self._write_status(result.status, state)
            return result

        # Debounce: espera arquivo estabilizar antes de commitar
        debounce = self.config.debounce_seconds
        now = self.clock.now()
        if debounce > 0:
            if (
                self._pending_fingerprint is None
                or self._pending_fingerprint != current
            ):
                self._pending_fingerprint = current
                self._pending_since = now
                result = PollResult(False, False, "Aguardando estabilizar arquivo")
                self._write_status(result.status, state)
                return result
            assert self._pending_since is not None
            elapsed = (now - self._pending_since).total_seconds()
            if elapsed < debounce:
                result = PollResult(False, False, "Aguardando estabilizar arquivo")
                self._write_status(result.status, state)
                return result
            # stable -> proceed with pending fingerprint
            current = self._pending_fingerprint
            self._pending_fingerprint = None
            self._pending_since = None

        state.detected_changes_today += 1
        created_commit, action = self._sync_and_commit(current)
        self._last_fingerprint = current
        state.last_fingerprint = {
            "exists": current.exists,
            "size": current.size,
            "mtime_ns": current.mtime_ns,
            "sha256": current.sha256,
        }
        if created_commit:
            state.committed_changes_today += 1
        result = PollResult(
            detected_change=True,
            created_commit=created_commit,
            status=f"Mudanca detectada: arquivo {action}",
        )
        self._write_status(result.status, state)
        return result

    def _sync_and_commit(self, current: FileFingerprint) -> tuple[bool, str]:
        target_file = self.mirrored_file_path
        metadata_path = self.metadata_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)

        if current.exists:
            target_file.write_bytes(self.active_watched_file.read_bytes())
            action = "updated"
        else:
            if target_file.exists():
                target_file.unlink()
            action = "deleted"

        metadata = {
            "source_file": str(self.active_watched_file),
            "tracked_file": str(self.config.tracked_relative_path),
            "timestamp_utc": self.clock.now().isoformat(),
            "action": action,
            "sha256": current.sha256,
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        stage_paths(
            self.config.repository_path,
            self.config.tracked_relative_path,
            Path(".autocommiter") / "last-event.json",
        )
        if not has_staged_changes(
            self.config.repository_path, self.config.tracked_relative_path
        ):
            LOGGER.info("Change detected but no staged diff remained.")
            return False, action

        message = f"chore: sync watched file ({action})"
        commit(self.config.repository_path, message)
        LOGGER.info("Created commit for %s", action)

        if self.config.push_on_commit:
            try:
                push(self.config.repository_path)
                LOGGER.info("Pushed latest commit")
            except Exception:
                LOGGER.exception("Push failed; commit remains local")
        return True, action

    def randomize_watched_number(self) -> int:
        target_file = self.active_watched_file
        target_file.parent.mkdir(parents=True, exist_ok=True)
        generated_number = random.randint(100000, 999999)
        target_file.write_text(str(generated_number), encoding="utf-8")
        self._write_status(f"Arquivo alterado manualmente para {generated_number}")
        return generated_number

    def get_daily_state(self) -> DailyState:
        return self.state_store.load(today=self.clock.today())

    def resolve_today_note(self, today: datetime | None = None) -> Path:
        if self.config.daily_notes_directory is None:
            return self.config.watched_file
        current = today or self.clock.now()
        return self.config.daily_notes_directory / current.strftime("%d-%m-%Y.md")

    def _write_status(self, status: str, state: DailyState | None = None) -> None:
        current_state = state or self.state_store.load(today=self.clock.today())
        current_state.last_status = status
        self.state_store.save(current_state)

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import __version__
from .config import AppConfig, default_tracked_relative_path, load_config, save_config
from .service import Clock, PollResult, SystemClock, WatcherService
from .state import DailyStateStore
from .updater import UpdateCheckResult, UpdateManager


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    max_detections_per_day: int
    detected_changes_today: int
    committed_changes_today: int
    update_repository: str
    recent_commits: list[str]


@dataclass(frozen=True, slots=True)
class FileMonitorSnapshot:
    watched_file: str
    daily_notes_directory: str
    repository_path: str
    monitoring_status: str
    today_note_path: str
    today_note_created: bool
    today_note_identified: bool
    today_note_monitored: bool


class MonitorController:
    def __init__(
        self,
        config: AppConfig | None = None,
        state_store: DailyStateStore | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.state_store = state_store or DailyStateStore()
        self.config = config or load_config()
        self.clock = clock or SystemClock()
        self.service = WatcherService(
            self.config, state_store=self.state_store, clock=self.clock
        )
        self._initialized = False

    def ensure_initialized(self) -> None:
        if self._initialized:
            return
        self.service.initialize()
        self._initialized = True

    def dashboard_snapshot(self) -> DashboardSnapshot:
        state = self.service.get_daily_state()
        recent_commits: list[str] = []
        try:
            from .git_ops import run_git

            result = run_git(
                self.config.repository_path,
                "log",
                "-10",
                "--oneline",
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                recent_commits = [
                    line.strip() for line in result.stdout.splitlines() if line.strip()
                ]
            elif result.returncode != 0:
                recent_commits = []
        except Exception:
            recent_commits = ["(não foi possível ler o histórico)"]
        return DashboardSnapshot(
            max_detections_per_day=self.config.max_detections_per_day,
            detected_changes_today=state.detected_changes_today,
            committed_changes_today=state.committed_changes_today,
            update_repository=self.config.update_repository,
            recent_commits=recent_commits,
        )

    def file_snapshot(self, today: date | None = None) -> FileMonitorSnapshot:
        state = self.service.get_daily_state()
        today_note = self.today_note_path(today=today)
        active_file = self.service.active_watched_file
        # When `today` is injected (tests), compare against that date's note
        if today is not None and self.config.daily_notes_directory is None:
            # file-per-note without daily dir: use parent+today for determinism
            active_file = self.config.watched_file
        return FileMonitorSnapshot(
            watched_file=str(active_file),
            daily_notes_directory=(
                str(self.config.daily_notes_directory) if self.config.daily_notes_directory else ""
            ),
            repository_path=str(self.config.repository_path),
            monitoring_status=state.last_status,
            today_note_path=str(today_note),
            today_note_created=today_note.exists(),
            today_note_identified=self._is_daily_note_path(today_note),
            today_note_monitored=active_file.resolve() == today_note.resolve(),
        )

    def save_limits(self, max_detections_per_day: int) -> None:
        self.config.max_detections_per_day = max_detections_per_day
        save_config(self.config)

    def save_update_repository(self, repository: str) -> None:
        self.config.update_repository = repository.strip()
        save_config(self.config)

    def update_watched_file(self, watched_file: str) -> None:
        watched_path = Path(watched_file).expanduser().resolve()
        self.config.watched_file = watched_path
        self.config.daily_notes_directory = None
        self.config.tracked_relative_path = default_tracked_relative_path(watched_path)
        save_config(self.config)
        self.service = WatcherService(
            self.config, state_store=self.state_store, clock=self.clock
        )
        self._initialized = False

    def update_daily_notes_directory(self, notes_directory: str) -> None:
        directory = Path(notes_directory).expanduser().resolve()
        self.config.daily_notes_directory = directory
        today_note = self.today_note_path()
        self.config.watched_file = today_note
        self.config.tracked_relative_path = default_tracked_relative_path(today_note)
        save_config(self.config)
        self.service = WatcherService(
            self.config, state_store=self.state_store, clock=self.clock
        )
        self._initialized = False

    def update_repository_path(self, repository_path: str) -> None:
        self.config.repository_path = Path(repository_path).expanduser().resolve()
        save_config(self.config)
        self.service = WatcherService(
            self.config, state_store=self.state_store, clock=self.clock
        )
        self._initialized = False

    def poll_once(self) -> PollResult:
        self.ensure_initialized()
        return self.service.poll_once()

    def randomize_watched_number(self) -> int:
        return self.service.randomize_watched_number()

    def check_for_update(self) -> UpdateCheckResult | None:
        return UpdateManager(self.config, __version__).check_for_update()

    def download_update(self, result: UpdateCheckResult) -> Path:
        if result.selected_asset is None:
            raise RuntimeError("The latest release does not contain a supported asset.")
        return UpdateManager(self.config, __version__).download_update(result.selected_asset)

    def apply_update_on_restart(self, asset_path: Path, target_pid: int) -> None:
        UpdateManager(self.config, __version__).apply_update_on_restart(asset_path, target_pid)

    def today_note_path(self, today: date | None = None) -> Path:
        current_day = today or date.today()
        base_dir = self.config.daily_notes_directory or self.config.watched_file.parent
        return base_dir / f"{current_day.strftime('%d-%m-%Y')}.md"

    def monitor_today_note(self, today: date | None = None) -> Path:
        note_path = self.today_note_path(today=today)
        self.update_watched_file(str(note_path))
        return note_path

    def _is_daily_note_path(self, path: Path) -> bool:
        return path.suffix.lower() == ".md" and len(path.stem) == 10

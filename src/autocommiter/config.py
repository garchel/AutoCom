from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def app_data_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA environment variable is not available.")
    return Path(appdata) / "AutoCommiter"


def config_path() -> Path:
    return app_data_dir() / "config.json"


@dataclass(slots=True)
class AppConfig:
    watched_file: Path
    repository_path: Path
    tracked_relative_path: Path
    daily_notes_directory: Path | None = None
    update_repository: str = ""
    poll_interval_seconds: float = 5.0
    push_on_commit: bool = False
    max_detections_per_day: int = 100
    debounce_seconds: float = 0.0
    config_version: int = 1

    def to_json(self) -> str:
        payload = asdict(self)
        payload["watched_file"] = str(self.watched_file)
        payload["repository_path"] = str(self.repository_path)
        payload["tracked_relative_path"] = str(self.tracked_relative_path)
        payload["daily_notes_directory"] = (
            str(self.daily_notes_directory) if self.daily_notes_directory else None
        )
        payload["update_repository"] = self.update_repository
        payload["debounce_seconds"] = self.debounce_seconds
        payload["config_version"] = self.config_version
        return json.dumps(payload, indent=2)

    @classmethod
    def from_json(cls, raw: str) -> AppConfig:
        data = json.loads(raw)
        return cls(
            watched_file=Path(data["watched_file"]),
            repository_path=Path(data["repository_path"]),
            tracked_relative_path=Path(data["tracked_relative_path"]),
            daily_notes_directory=(
                Path(data["daily_notes_directory"])
                if data.get("daily_notes_directory")
                else None
            ),
            update_repository=str(data.get("update_repository", "")),
            poll_interval_seconds=float(data["poll_interval_seconds"]),
            push_on_commit=bool(data["push_on_commit"]),
            max_detections_per_day=int(data.get("max_detections_per_day", 100)),
            debounce_seconds=float(data.get("debounce_seconds", 1.5)),
            config_version=int(data.get("config_version", 1)),
        )


def default_tracked_relative_path(watched_file: Path) -> Path:
    suffix = watched_file.suffix or ".txt"
    return Path("tracked") / f"{watched_file.stem}{suffix}"


def validate_config(config: AppConfig) -> AppConfig:
    if config.poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be greater than zero.")
    if config.max_detections_per_day <= 0:
        raise ValueError("max_detections_per_day must be greater than zero.")
    if config.debounce_seconds < 0:
        raise ValueError("debounce_seconds must be >= 0.")
    if config.debounce_seconds >= config.poll_interval_seconds:
        # Warn but allow - debounce should be smaller than poll
        pass
    if config.daily_notes_directory is not None and not config.daily_notes_directory.is_absolute():
        raise ValueError("daily_notes_directory must be an absolute path when configured.")
    if config.update_repository and config.update_repository.count("/") != 1:
        raise ValueError("update_repository must use the format owner/repo.")
    if config.tracked_relative_path.is_absolute():
        raise ValueError("tracked_relative_path must be relative to the repository root.")

    repo_root = config.repository_path.resolve(strict=False)
    # Strict symlink check: ensure tracked stays inside repo after resolving symlinks
    tracked_path = (repo_root / config.tracked_relative_path).resolve()
    if not tracked_path.is_relative_to(repo_root):
        raise ValueError("tracked_relative_path must stay inside the repository.")
    try:
        # Extra symlink traversal guard
        tracked_path.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError("tracked_relative_path escapes repository via symlink") from exc
    if config.daily_notes_directory is not None:
        if config.daily_notes_directory.is_absolute():
            daily_resolved = config.daily_notes_directory.resolve()
            if not daily_resolved.is_relative_to(repo_root):
                # Vault do Obsidian fora do repo é um caso de uso esperado
                pass
    return config


def save_config(config: AppConfig) -> Path:
    validate_config(config)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.to_json(), encoding="utf-8")
    return path


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Configuração não encontrada em {path}. "
            "Rode 'autocommiter configure' ou '.\\scripts\\install.ps1' para criar."
        )
    config = AppConfig.from_json(path.read_text(encoding="utf-8"))
    # Valida ao carregar para falhar cedo com mensagem clara
    validate_config(config)
    return config

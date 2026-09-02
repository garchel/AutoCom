from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest

from autocommiter import service
from autocommiter.config import AppConfig, validate_config
from autocommiter.controller import MonitorController
from autocommiter.service import WatcherService
from autocommiter.state import DailyStateStore
from autocommiter.updater import (
    ReleaseAsset,
    ReleaseInfo,
    UpdateManager,
    is_newer_version,
    select_release_asset,
)


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def create_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def test_commits_when_watched_file_changes(tmp_path: Path) -> None:
    watched_file = tmp_path / "source.txt"
    watched_file.write_text("first", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    create_repo(repo)

    state_store = DailyStateStore(tmp_path / "state.json")
    service = WatcherService(
        AppConfig(
            watched_file=watched_file,
            repository_path=repo,
            tracked_relative_path=Path("tracked/source.txt"),
            daily_notes_directory=None,
            poll_interval_seconds=1,
            push_on_commit=False,
            max_detections_per_day=10,
        ),
        state_store=state_store,
    )
    service.initialize()

    watched_file.write_text("second", encoding="utf-8")
    result = service.poll_once()

    assert result.detected_change is True
    assert result.created_commit is True
    assert (repo / "tracked/source.txt").read_text(encoding="utf-8") == "second"
    assert run_git(repo, "rev-list", "--count", "HEAD") == "1"
    state = state_store.load()
    assert state.detected_changes_today == 1
    assert state.committed_changes_today == 1


def test_does_not_commit_when_file_is_unchanged(tmp_path: Path) -> None:
    watched_file = tmp_path / "source.txt"
    watched_file.write_text("same", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    create_repo(repo)

    service = WatcherService(
        AppConfig(
            watched_file=watched_file,
            repository_path=repo,
            tracked_relative_path=Path("tracked/source.txt"),
            daily_notes_directory=None,
            poll_interval_seconds=1,
            push_on_commit=False,
            max_detections_per_day=10,
        ),
        state_store=DailyStateStore(tmp_path / "state.json"),
    )
    service.initialize()

    result = service.poll_once()

    assert result.detected_change is False
    assert run_git(repo, "rev-list", "--all", "--count") == "0"


def test_commits_change_detected_after_restart(tmp_path: Path) -> None:
    watched_file = tmp_path / "source.txt"
    watched_file.write_text("new-content", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    create_repo(repo)
    tracked_file = repo / "tracked/source.txt"
    tracked_file.parent.mkdir(parents=True)
    tracked_file.write_text("old-content", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    service = WatcherService(
        AppConfig(
            watched_file=watched_file,
            repository_path=repo,
            tracked_relative_path=Path("tracked/source.txt"),
            daily_notes_directory=None,
            poll_interval_seconds=1,
            push_on_commit=False,
            max_detections_per_day=10,
        ),
        state_store=DailyStateStore(tmp_path / "state.json"),
    )
    service.initialize()

    result = service.poll_once()

    assert result.detected_change is True
    assert tracked_file.read_text(encoding="utf-8") == "new-content"
    assert run_git(repo, "rev-list", "--count", "HEAD") == "2"


def test_rejects_tracked_path_outside_repository(tmp_path: Path) -> None:
    config = AppConfig(
        watched_file=tmp_path / "source.txt",
        repository_path=tmp_path / "repo",
        tracked_relative_path=Path("../outside.txt"),
        daily_notes_directory=None,
        poll_interval_seconds=1,
        push_on_commit=False,
        max_detections_per_day=1,
    )

    with pytest.raises(ValueError):
        validate_config(config)


def test_push_failure_keeps_single_local_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    watched_file = tmp_path / "source.txt"
    watched_file.write_text("first", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    create_repo(repo)

    def fail_push(_: Path) -> None:
        raise RuntimeError("push failed")

    monkeypatch.setattr(service, "push", fail_push)

    watcher = WatcherService(
        AppConfig(
            watched_file=watched_file,
            repository_path=repo,
            tracked_relative_path=Path("tracked/source.txt"),
            daily_notes_directory=None,
            poll_interval_seconds=1,
            push_on_commit=True,
            max_detections_per_day=10,
        ),
        state_store=DailyStateStore(tmp_path / "state.json"),
    )
    watcher.initialize()

    watched_file.write_text("second", encoding="utf-8")
    changed = watcher.poll_once()
    repeated = watcher.poll_once()

    assert changed.detected_change is True
    assert repeated.detected_change is False
    assert run_git(repo, "rev-list", "--count", "HEAD") == "1"


def test_stops_detecting_changes_after_daily_limit(tmp_path: Path) -> None:
    watched_file = tmp_path / "source.txt"
    watched_file.write_text("one", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    create_repo(repo)
    state_store = DailyStateStore(tmp_path / "state.json")

    watcher = WatcherService(
        AppConfig(
            watched_file=watched_file,
            repository_path=repo,
            tracked_relative_path=Path("tracked/source.txt"),
            daily_notes_directory=None,
            poll_interval_seconds=1,
            push_on_commit=False,
            max_detections_per_day=1,
        ),
        state_store=state_store,
    )
    watcher.initialize()

    watched_file.write_text("two", encoding="utf-8")
    first = watcher.poll_once()
    watched_file.write_text("three", encoding="utf-8")
    second = watcher.poll_once()

    assert first.detected_change is True
    assert second.limit_reached is True
    assert state_store.load().detected_changes_today == 1
    assert run_git(repo, "rev-list", "--count", "HEAD") == "1"


def test_randomizes_watched_number(tmp_path: Path) -> None:
    watched_file = tmp_path / "source.txt"
    repo = tmp_path / "repo"
    repo.mkdir()
    create_repo(repo)

    watcher = WatcherService(
        AppConfig(
            watched_file=watched_file,
            repository_path=repo,
            tracked_relative_path=Path("tracked/source.txt"),
            daily_notes_directory=None,
            poll_interval_seconds=1,
            push_on_commit=False,
            max_detections_per_day=10,
        )
    )

    generated = watcher.randomize_watched_number()

    assert watched_file.read_text(encoding="utf-8") == str(generated)
    assert 100000 <= generated <= 999999


def test_controller_updates_daily_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    watched_file = tmp_path / "source.txt"
    watched_file.write_text("1", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    create_repo(repo)
    state_store = DailyStateStore(tmp_path / "state.json")
    config = AppConfig(
        watched_file=watched_file,
        repository_path=repo,
        tracked_relative_path=Path("tracked/source.txt"),
        daily_notes_directory=None,
        poll_interval_seconds=1,
        push_on_commit=False,
        max_detections_per_day=5,
    )
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))

    controller = MonitorController(config=config, state_store=state_store)
    controller.save_limits(9)

    assert controller.dashboard_snapshot().max_detections_per_day == 9


def test_controller_updates_update_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    create_repo(repo)
    controller = MonitorController(
        config=AppConfig(
            watched_file=tmp_path / "source.txt",
            repository_path=repo,
            tracked_relative_path=Path("tracked/source.txt"),
            daily_notes_directory=None,
            update_repository="",
            poll_interval_seconds=1,
            push_on_commit=False,
            max_detections_per_day=5,
        ),
        state_store=DailyStateStore(tmp_path / "state.json"),
    )

    controller.save_update_repository("owner/project")

    assert controller.dashboard_snapshot().update_repository == "owner/project"


def test_file_snapshot_reports_today_note_status(tmp_path: Path) -> None:
    notes_dir = tmp_path / "Estudos Diarios"
    notes_dir.mkdir()
    today = date(2026, 7, 6)
    today_note = notes_dir / "06-07-2026.md"
    today_note.write_text("# nota", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    create_repo(repo)
    config = AppConfig(
        watched_file=today_note,
        repository_path=repo,
        tracked_relative_path=Path("tracked/06-07-2026.md"),
        daily_notes_directory=None,
        poll_interval_seconds=1,
        push_on_commit=False,
        max_detections_per_day=5,
    )

    controller = MonitorController(
        config=config,
        state_store=DailyStateStore(tmp_path / "state.json"),
    )
    snapshot = controller.file_snapshot(today=today)

    assert controller.today_note_path(today=today) == today_note
    assert snapshot.today_note_path.endswith("06-07-2026.md")
    assert snapshot.today_note_created is True
    assert snapshot.today_note_identified is True
    assert snapshot.today_note_monitored is True
    assert snapshot.daily_notes_directory == ""


def test_controller_can_switch_to_today_note(tmp_path: Path) -> None:
    notes_dir = tmp_path / "Estudos Diarios"
    notes_dir.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    create_repo(repo)
    old_note = notes_dir / "05-07-2026.md"
    old_note.write_text("# ontem", encoding="utf-8")
    today = date(2026, 7, 6)
    today_note = notes_dir / "06-07-2026.md"

    controller = MonitorController(
        config=AppConfig(
            watched_file=old_note,
            repository_path=repo,
            tracked_relative_path=Path("tracked/05-07-2026.md"),
            daily_notes_directory=None,
            poll_interval_seconds=1,
            push_on_commit=False,
            max_detections_per_day=5,
        ),
        state_store=DailyStateStore(tmp_path / "state.json"),
    )

    switched = controller.monitor_today_note(today=today)

    assert switched == today_note
    assert controller.file_snapshot().watched_file.endswith("06-07-2026.md")


def test_service_auto_discovers_today_note_from_directory(tmp_path: Path) -> None:
    notes_dir = tmp_path / "Estudos Diarios"
    notes_dir.mkdir()
    today_note = notes_dir / date.today().strftime("%d-%m-%Y.md")
    today_note.write_text("primeira", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    create_repo(repo)

    watcher = WatcherService(
        AppConfig(
            watched_file=notes_dir / "placeholder.md",
            repository_path=repo,
            tracked_relative_path=Path("tracked/today.md"),
            daily_notes_directory=notes_dir.resolve(),
            poll_interval_seconds=1,
            push_on_commit=False,
            max_detections_per_day=5,
        ),
        state_store=DailyStateStore(tmp_path / "state.json"),
    )
    watcher.initialize()
    today_note.write_text("segunda", encoding="utf-8")

    result = watcher.poll_once()

    assert watcher.active_watched_file == today_note
    assert result.detected_change is True


def test_controller_updates_daily_notes_directory(tmp_path: Path) -> None:
    notes_dir = tmp_path / "Estudos Diarios"
    notes_dir.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    create_repo(repo)
    controller = MonitorController(
        config=AppConfig(
            watched_file=tmp_path / "old.md",
            repository_path=repo,
            tracked_relative_path=Path("tracked/old.md"),
            daily_notes_directory=None,
            poll_interval_seconds=1,
            push_on_commit=False,
            max_detections_per_day=5,
        ),
        state_store=DailyStateStore(tmp_path / "state.json"),
    )

    controller.update_daily_notes_directory(str(notes_dir))
    snapshot = controller.file_snapshot()

    assert snapshot.daily_notes_directory == str(notes_dir.resolve())
    assert snapshot.watched_file.endswith(date.today().strftime("%d-%m-%Y.md"))


def test_version_comparison_detects_newer_release() -> None:
    assert is_newer_version("0.1.0", "v0.2.0") is True
    assert is_newer_version("0.2.0", "v0.2.0") is False


def test_select_release_asset_prefers_wheel() -> None:
    assets = [
        ReleaseAsset("autocommiter-0.2.0.zip", "https://example.com/file.zip", "application/zip"),
        ReleaseAsset(
            "autocommiter-0.2.0-py3-none-any.whl",
            "https://example.com/file.whl",
            "application/octet-stream",
        ),
    ]

    selected = select_release_asset(assets)

    assert selected is not None
    assert selected.name.endswith(".whl")


def test_update_manager_returns_update_result_when_newer_release_available(tmp_path: Path) -> None:
    class FakeClient:
        def latest_release(self) -> ReleaseInfo:
            return ReleaseInfo(
                tag_name="v0.2.0",
                name="v0.2.0",
                body="Release",
                html_url="https://github.com/owner/project/releases/tag/v0.2.0",
                assets=[
                    ReleaseAsset(
                        "autocommiter-0.2.0-py3-none-any.whl",
                        "https://example.com/file.whl",
                        "application/octet-stream",
                    )
                ],
            )

    manager = UpdateManager(
        AppConfig(
            watched_file=tmp_path / "source.txt",
            repository_path=tmp_path / "repo",
            tracked_relative_path=Path("tracked/source.txt"),
            daily_notes_directory=None,
            update_repository="owner/project",
            poll_interval_seconds=1,
            push_on_commit=False,
            max_detections_per_day=5,
        ),
        current_version="0.1.0",
        client=FakeClient(),  # type: ignore[arg-type]
    )

    result = manager.check_for_update()

    assert result is not None
    assert result.latest_version == "v0.2.0"
    assert result.selected_asset is not None

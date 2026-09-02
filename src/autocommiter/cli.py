from __future__ import annotations

import argparse
import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import (
    AppConfig,
    app_data_dir,
    config_path,
    default_tracked_relative_path,
    load_config,
    save_config,
)
from .controller import MonitorController
from .gui import AutoCommiterApp
from .service import WatcherService
from .state import state_path
from .windows import install_autostart, is_autostart_installed, uninstall_autostart


def _setup_logging() -> None:
    log_dir = app_data_dir() / "Logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "autocommiter.log"
    handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # Keep stdout handler if running interactively (stderr for errors)
    has_stderr = any(
        isinstance(h, logging.StreamHandler)
        and getattr(h, "stream", None) is sys.stderr
        for h in root.handlers
    )
    if not has_stderr:
        stderr = logging.StreamHandler()
        stderr.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        root.addHandler(stderr)


def _warn_self_tracking_repo(repo: Path) -> None:
    # Avisa se repo de dados é o próprio repo do app (mistura código + dados)
    pyproject = repo / "pyproject.toml"
    src_marker = repo / "src" / "autocommiter"
    if pyproject.exists() or src_marker.exists():
        print(
            "Aviso: repository_path parece ser o próprio repositório do app. "
            "Recomenda-se usar um repositório dedicado para os dados (ex: repo-privado)."
        )


def _install_excepthook() -> None:
    def _handler(exc_type, exc_value, exc_tb) -> None:
        logging.getLogger().critical(
            "Unhandled exception: %s", "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        )
    sys.excepthook = _handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autocommiter")
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure_parser = subparsers.add_parser("configure")
    configure_parser.add_argument("--watched-file", required=True)
    configure_parser.add_argument("--repository-path", required=True)
    configure_parser.add_argument("--tracked-relative-path")
    configure_parser.add_argument("--daily-notes-directory")
    configure_parser.add_argument("--update-repository", default="")
    configure_parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    configure_parser.add_argument("--push-on-commit", action="store_true")
    configure_parser.add_argument("--max-detections-per-day", type=int, default=100)
    configure_parser.add_argument("--debounce-seconds", type=float, default=1.5)

    subparsers.add_parser("run")
    subparsers.add_parser("once")
    gui_parser = subparsers.add_parser("gui")
    gui_parser.add_argument("--start-minimized", action="store_true")
    subparsers.add_parser("install-autostart")
    subparsers.add_parser("uninstall-autostart")
    subparsers.add_parser("status")
    subparsers.add_parser("doctor")
    return parser


def configure_command(args: argparse.Namespace) -> int:
    watched_file = Path(args.watched_file).expanduser().resolve()
    repository_path = Path(args.repository_path).expanduser().resolve()
    tracked_relative_path = (
        Path(args.tracked_relative_path)
        if args.tracked_relative_path
        else default_tracked_relative_path(watched_file)
    )

    daily_notes_dir = None
    if args.daily_notes_directory:
        daily_notes_dir = Path(args.daily_notes_directory).expanduser().resolve()
        if not daily_notes_dir.exists():
            print(f"Aviso: pasta de notas diarias nao existe, criando: {daily_notes_dir}")
            daily_notes_dir.mkdir(parents=True, exist_ok=True)

    config = AppConfig(
        watched_file=watched_file,
        repository_path=repository_path,
        tracked_relative_path=tracked_relative_path,
        daily_notes_directory=daily_notes_dir,
        update_repository=args.update_repository,
        poll_interval_seconds=args.poll_interval_seconds,
        push_on_commit=args.push_on_commit,
        max_detections_per_day=args.max_detections_per_day,
        debounce_seconds=args.debounce_seconds,
    )
    save_config(config)
    print(f"Configuracao salva em {config_path()}")
    # Validação amigável pós-save
    if not repository_path.exists():
        print(
            f"Aviso: repository_path nao existe: {repository_path} "
            "-> crie a pasta e rode 'git init'"
        )
    elif not (repository_path / ".git").exists():
        print(f"Aviso: {repository_path} nao tem .git -> rode 'git init' dentro da pasta")
    if daily_notes_dir and not daily_notes_dir.exists():
        print(f"Aviso: daily_notes_directory ainda nao existe: {daily_notes_dir}")
    _warn_self_tracking_repo(repository_path)
    return 0


def run_command(run_once: bool) -> int:
    config = load_config()
    service = WatcherService(config)
    if run_once:
        service.initialize()
        service.poll_once()
        return 0
    service.run_forever()
    return 0


def gui_command(start_minimized: bool) -> int:
    controller = MonitorController()
    app = AutoCommiterApp(controller, start_minimized=start_minimized)
    app.run()
    return 0


def status_command() -> int:
    print("=== AutoCommiter status ===")
    cfg_path = config_path()
    st_path = state_path()
    print(f"Config: {cfg_path} (exists={cfg_path.exists()})")
    print(f"State: {st_path} (exists={st_path.exists()})")
    try:
        config = load_config()
        watched_exists = (
            config.watched_file.exists()
            if not config.daily_notes_directory
            else "daily-note mode"  # noqa: E501
        )
        # Exists is dynamic, keep line within limit via variable
        print(f"watched_file: {config.watched_file} (exists={watched_exists})")
        if config.daily_notes_directory:
            exists = config.daily_notes_directory.exists()
            print(f"daily_notes_directory: {config.daily_notes_directory} (exists={exists})")
            # resolve today note via controller to reuse formatting
            ctrl = MonitorController(config=config)
            today_note = ctrl.today_note_path()
            print(f"today_note: {today_note} (exists={today_note.exists()})")
        repo_exists = config.repository_path.exists()
        print(f"repository_path: {config.repository_path} (exists={repo_exists})")
        is_git = (config.repository_path / ".git").exists()
        print(f"is_git_repo: {is_git}")
        if is_git:
            import subprocess

            result = subprocess.run(
                ["git", "-C", str(config.repository_path), "status", "--porcelain", "-b"],
                capture_output=True,
                text=True,
            )
            print(f"git status: {result.stdout.strip()[:500] or '(clean)'}")
            if result.stderr:
                print(f"git stderr: {result.stderr.strip()[:500]}")
        print(f"tracked_relative_path: {config.tracked_relative_path}")
        print(f"poll_interval_seconds: {config.poll_interval_seconds}")
        print(f"debounce_seconds: {config.debounce_seconds}")
        print(f"max_detections_per_day: {config.max_detections_per_day}")
        print(f"push_on_commit: {config.push_on_commit}")
        print(f"update_repository: {config.update_repository or '(none)'}")
        if st_path.exists():
            print("--- state ---")
            print(st_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        print(f"ERRO: {exc}")
        print(
            "Rode: .venv\\Scripts\\python -m autocommiter configure ... "
            "ou .\\scripts\\install.ps1 -WatchedFile ... -RepositoryPath ..."
        )
        return 1
    except Exception as exc:
        print(f"ERRO ao carregar config: {exc}")
        return 1

    print(f"autostart instalado: {is_autostart_installed()}")
    if not is_autostart_installed():
        print("Dica: .venv\\Scripts\\python -m autocommiter install-autostart")
    print(
        "OK - verifique os itens acima. "
        "Se repository nao for git, rode: git init <repo> && git config user.name/email"
    )
    return 0


def main() -> int:
    _setup_logging()
    _install_excepthook()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "configure":
        return configure_command(args)
    if args.command == "run":
        return run_command(run_once=False)
    if args.command == "once":
        return run_command(run_once=True)
    if args.command == "gui":
        return gui_command(start_minimized=args.start_minimized)
    if args.command == "install-autostart":
        install_autostart()
        print("Autostart instalado.")
        return 0
    if args.command == "uninstall-autostart":
        uninstall_autostart()
        print("Autostart removido.")
        return 0
    if args.command in ("status", "doctor"):
        return status_command()
    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

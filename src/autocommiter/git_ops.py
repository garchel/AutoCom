from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise GitError(result.stderr.strip() or result.stdout.strip() or "Git command failed.")
    return result


def ensure_repository(repo: Path) -> None:
    if not repo.exists():
        raise GitError(
            f"Repositório não encontrado: {repo}. "
            f"Crie a pasta e rode 'git init' ou reconfigure com um caminho válido."
        )
    result = run_git(repo, "rev-parse", "--is-inside-work-tree", check=False)
    if result.returncode != 0:
        raise GitError(
            f"Diretório não é um repositório Git: {repo}. "
            f"Rode 'git init' em {repo} ou aponte --repository-path para um repo válido. "
            f"Detalhe: {result.stderr.strip() or result.stdout.strip()}"
        )


def stage_paths(repo: Path, *paths: Path) -> None:
    relative_paths = [str(path) for path in paths]
    run_git(repo, "add", "--", *relative_paths)


def has_staged_changes(repo: Path, tracked_relative: Path) -> bool:
    tracked_str = str(tracked_relative)
    result = run_git(repo, "diff", "--cached", "--quiet", "--", tracked_str, check=False)
    if result.returncode == 1:
        return True
    # Falls back to tracked-only porcelain when --cached diff is inconclusive
    porcelain = run_git(repo, "status", "--porcelain", "--", tracked_str, check=False)
    return bool(porcelain.stdout.strip())


def commit(repo: Path, message: str) -> None:
    run_git(repo, "commit", "-m", message)


def push(repo: Path) -> None:
    run_git(repo, "push")


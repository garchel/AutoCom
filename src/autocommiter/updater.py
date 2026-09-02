from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import request

from .config import AppConfig, app_data_dir

GITHUB_API_VERSION = "2026-03-10"


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    browser_download_url: str
    content_type: str
    digest: str | None = None
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    tag_name: str
    name: str
    body: str
    html_url: str
    assets: list[ReleaseAsset]


@dataclass(frozen=True, slots=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str
    release: ReleaseInfo
    selected_asset: ReleaseAsset | None


def normalize_version(version: str) -> tuple[int, ...]:
    cleaned = version.strip().removeprefix("v")
    parts = cleaned.split(".")
    normalized: list[int] = []
    for part in parts:
        digits = "".join(character for character in part if character.isdigit())
        normalized.append(int(digits or "0"))
    return tuple(normalized)


def is_newer_version(current_version: str, latest_version: str) -> bool:
    return normalize_version(latest_version) > normalize_version(current_version)


def select_release_asset(assets: list[ReleaseAsset]) -> ReleaseAsset | None:
    priorities = (".whl", ".tar.gz", ".exe", ".msi")
    for suffix in priorities:
        for asset in assets:
            if asset.name.endswith(suffix):
                return asset
    return assets[0] if assets else None


class GitHubReleasesClient:
    def __init__(self, repository: str) -> None:
        self.repository = repository

    def latest_release(self) -> ReleaseInfo:
        api_url = f"https://api.github.com/repos/{self.repository}/releases/latest"
        http_request = request.Request(
            api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
                "User-Agent": "AutoCommiter-Updater",
            },
        )
        with request.urlopen(http_request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return ReleaseInfo(
            tag_name=str(payload["tag_name"]),
            name=str(payload.get("name", payload["tag_name"])),
            body=str(payload.get("body", "")),
            html_url=str(payload["html_url"]),
            assets=[
                ReleaseAsset(
                    name=str(asset["name"]),
                    browser_download_url=str(asset["browser_download_url"]),
                    content_type=str(asset.get("content_type", "")),
                    sha256=str(asset.get("sha256", "")).lower()
                    or str(asset.get("digest", "")).lower()
                    or None,
                )
                for asset in payload.get("assets", [])
            ],
        )


class UpdateManager:
    def __init__(
        self,
        config: AppConfig,
        current_version: str,
        client: GitHubReleasesClient | None = None,
    ) -> None:
        self.config = config
        self.current_version = current_version
        self.client = client or GitHubReleasesClient(config.update_repository)

    def check_for_update(self) -> UpdateCheckResult | None:
        if not self.config.update_repository:
            return None
        release = self.client.latest_release()
        if not is_newer_version(self.current_version, release.tag_name):
            return None
        return UpdateCheckResult(
            current_version=self.current_version,
            latest_version=release.tag_name,
            release=release,
            selected_asset=select_release_asset(release.assets),
        )

    def download_update(self, asset: ReleaseAsset) -> Path:
        download_dir = app_data_dir() / "updates"
        download_dir.mkdir(parents=True, exist_ok=True)
        destination = download_dir / asset.name
        http_request = request.Request(
            asset.browser_download_url,
            headers={"User-Agent": "AutoCommiter-Updater"},
        )
        with request.urlopen(http_request, timeout=60) as response:
            destination.write_bytes(response.read())
        if asset.sha256:
            actual = hashlib.sha256(destination.read_bytes()).hexdigest().lower()
            if actual != asset.sha256.lower():
                destination.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Hash do asset baixado ({actual}) difere do esperado ({asset.sha256}). "
                    "Download abortado por integridade."
                )
        return destination

    def apply_update_on_restart(self, asset_path: Path, target_pid: int) -> None:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "autocommiter.updater_apply",
                str(asset_path),
                str(target_pid),
            ],
            close_fds=True,
        )


def install_asset(asset_path: Path) -> None:
    if asset_path.suffix == ".whl" or asset_path.name.endswith(".tar.gz"):
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", str(asset_path)],
            check=True,
        )
        return
    if asset_path.suffix == ".exe":
        subprocess.Popen([str(asset_path)])
        return
    if asset_path.suffix == ".msi":
        subprocess.Popen(["msiexec", "/i", str(asset_path)])
        return
    raise RuntimeError(f"Unsupported update asset: {asset_path.name}")


def wait_for_process_exit(pid: int, timeout_seconds: float = 60.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        command = f"Get-Process -Id {pid} -ErrorAction SilentlyContinue"
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
        )
        if not result.stdout.strip():
            return
        time.sleep(0.5)
    raise TimeoutError("Timed out waiting for process exit.")


def restart_application() -> None:
    subprocess.Popen([sys.executable, "-m", "autocommiter", "gui"])

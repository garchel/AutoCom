from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isola APPDATA por teste para evitar poluir %APPDATA%\\AutoCommiter real."""
    isolated = tmp_path / "_appdata"
    isolated.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("APPDATA", str(isolated))
    return isolated

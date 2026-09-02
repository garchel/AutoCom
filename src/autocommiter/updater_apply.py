from __future__ import annotations

import sys
from pathlib import Path

from .updater import install_asset, restart_application, wait_for_process_exit


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python -m autocommiter.updater_apply <asset-path> <pid>")
    asset_path = Path(sys.argv[1]).resolve()
    pid = int(sys.argv[2])
    wait_for_process_exit(pid)
    install_asset(asset_path)
    restart_application()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

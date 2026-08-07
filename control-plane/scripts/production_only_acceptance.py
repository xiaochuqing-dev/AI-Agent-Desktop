"""Production-only installation and import smoke test.

This script is intentionally small so CI and the Windows candidate builder can
run it without installing test-only packages into the runtime environment.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result: dict[str, object] = {
        "python": sys.version.split()[0],
        "production_dependencies_only": True,
        "pip_install": "skipped" if args.skip_install else "pending",
        "lock_file": "requirements-prod.lock",
        "health_check": False,
        "real_telegram_access": False,
    }
    project_root: Path | None = None
    if not args.skip_install:
        project_root = Path(__file__).resolve().parents[1]
        lock_file = project_root / "requirements-prod.lock"
        build_lock_file = project_root / "requirements-build.lock"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "-r",
                str(build_lock_file),
            ],
            cwd=project_root,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "-r",
                str(lock_file),
            ],
            cwd=project_root,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-build-isolation",
                "-e",
                ".",
            ],
            cwd=project_root,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        result["pip_install"] = "passed"
        # The editable finder is installed after this interpreter starts. Add the
        # source root explicitly so the smoke import works in the same process.
        sys.path.insert(0, str(project_root))
    with tempfile.TemporaryDirectory(prefix="control-plane-production-") as data_dir:
        os.environ["CONTROL_PLANE_API_TOKEN"] = "production-smoke-token-0123456789"
        os.environ["CONTROL_PLANE_DISABLE_LIVE_TELEGRAM"] = "1"
        from control_plane.api.app import create_app
        from control_plane.infrastructure.config import Settings

        app = create_app(Settings(data_dir=data_dir), adapters=[])
        from fastapi.testclient import TestClient

        with TestClient(app, base_url="http://127.0.0.1") as client:
            client.headers["Authorization"] = "Bearer " + os.environ["CONTROL_PLANE_API_TOKEN"]
            response = client.get("/api/v1/system")
            response.raise_for_status()
            result["health_check"] = response.json()["api_version"] == "v1"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["health_check"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

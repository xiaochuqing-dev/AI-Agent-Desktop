from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def ensure_standard_streams() -> None:
    """Provide writable streams for libraries used by a windowed PyInstaller build."""

    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def candidate_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def main() -> int:
    ensure_standard_streams()
    parser = argparse.ArgumentParser(description="AI-Agent-Desktop acceptance candidate")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--serve", action="store_true", help="start the loopback Control Plane")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()
    root = candidate_root()
    if args.version:
        print("0.1.0-stage-a")
        return 0
    if args.serve:
        from control_plane.main import main as serve_control_plane

        serve_control_plane()
        return 0
    from control_plane.validation.wizard import (
        ValidationWizard,
        cleanup_validation_data,
        export_redacted_report,
        run_headless_checks,
    )

    if args.cleanup:
        removed = cleanup_validation_data(root)
        print(json.dumps({"status": "cleaned", "removed": removed}, ensure_ascii=True))
        return 0
    report = run_headless_checks(root)
    if args.headless:
        payload = json.dumps(report, ensure_ascii=True, indent=2)
        if args.json_output:
            export_redacted_report(report, args.json_output)
        print(payload)
        return 0
    ValidationWizard(candidate_root=root).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

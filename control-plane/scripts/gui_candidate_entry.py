from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

VERSION = "0.4.1-prebeta"


def ensure_standard_streams() -> None:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def main() -> int:
    ensure_standard_streams()
    parser = argparse.ArgumentParser(description="AI Agent Desktop GUI candidate")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--api-url")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()
    if args.version:
        print(VERSION)
        return 0
    if args.headless:
        print(json.dumps({"status": "ready", "version": VERSION, "gui": "pyside6"}))
        return 0
    from control_plane.gui.app import run

    argv: list[str] = ["--demo"] if args.demo else []
    if args.screenshot:
        argv.extend(["--screenshot", str(args.screenshot)])
    if args.api_url:
        argv.extend(["--api-url", args.api_url])
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())

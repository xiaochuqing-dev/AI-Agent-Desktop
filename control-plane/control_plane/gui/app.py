from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .api_client import (
    DemoControlPlaneClient,
    EmbeddedControlPlaneClient,
    HttpControlPlaneClient,
    candidate_artifact_dir,
)
from .main_window import MainWindow
from .widgets import ASSET_DIR

APP_VERSION = "0.4.1-prebeta"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Agent Desktop PySide6 GUI")
    parser.add_argument("--demo", action="store_true", help="Use synthetic local state.")
    parser.add_argument("--version", action="store_true", help="Print version and exit.")
    parser.add_argument("--screenshot", help="Save a startup screenshot and exit.")
    parser.add_argument("--api-url", help="Use an already-running loopback Control Plane.")
    return parser


def build_client(*, force_demo: bool, api_url: str | None = None):
    if force_demo:
        return DemoControlPlaneClient(), True
    token = os.environ.get("CONTROL_PLANE_API_TOKEN", "")
    base_url = api_url or os.environ.get("AI_AGENT_DESKTOP_API_URL", "")
    if token and not base_url:
        base_url = "http://127.0.0.1:58080"
    if token and base_url:
        return HttpControlPlaneClient(base_url, token), False
    return EmbeddedControlPlaneClient(artifact_dir=candidate_artifact_dir()), False


def _single_instance_lock() -> QLockFile:
    app_data = Path(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    )
    app_data.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(app_data / "ai-agent-desktop.lock"))
    if not lock.tryLock(100):
        raise RuntimeError("AI_AGENT_DESKTOP_ALREADY_RUNNING")
    return lock


def run(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.version:
        print(f"AI Agent Desktop {APP_VERSION}")
        return 0

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv[:1])
    app.setApplicationName("AI Agent Desktop")
    app.setOrganizationName("AI Agent Desktop")
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon(str(ASSET_DIR / "app_icon.ico")))
    try:
        instance_lock = _single_instance_lock()
    except RuntimeError:
        box = QMessageBox()
        box.setWindowTitle("AI Agent Desktop")
        box.setText("AI Agent Desktop 已经在运行。")
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
        return 0
    client, demo_mode = build_client(force_demo=args.demo, api_url=args.api_url)
    window = MainWindow(client, demo_mode=demo_mode)
    window.show()
    close_client = getattr(client, "close", None)
    if callable(close_client):
        app.aboutToQuit.connect(close_client)
    app.aboutToQuit.connect(instance_lock.unlock)

    if args.screenshot:
        target = Path(args.screenshot).resolve()

        def save_and_exit() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(target), "PNG")
            app.quit()

        QTimer.singleShot(900, save_and_exit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon

ICON_ASSET_DIR = Path(__file__).with_name("assets")
ICON_NAMES = (
    "arrow-left",
    "arrow-right",
    "claude",
    "clipboard",
    "close",
    "codex",
    "eye-off",
    "eye",
    "group",
    "hermes",
    "info",
    "maximize",
    "minimize",
    "qr",
    "refresh",
    "repair",
    "restore",
    "shield",
    "success",
    "telegram",
    "warning",
    "error",
)


class IconRegistry:
    """Resolve only the small icon subset shipped with the application."""

    @classmethod
    def path(cls, name: str) -> Path:
        if name not in ICON_NAMES:
            raise KeyError(f"Unknown GUI icon: {name}")
        return ICON_ASSET_DIR / f"{name}.svg"

    @classmethod
    def get(cls, name: str) -> QIcon:
        return QIcon(str(cls.path(name)))


def icon(name: str) -> QIcon:
    return IconRegistry.get(name)

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QPushButton

from .registry import icon


class IconButton(QPushButton):
    """A stable hit target for icon-only controls."""

    def __init__(self, icon_name: str, *, tooltip: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("IconButton")
        self.setIcon(icon(icon_name))
        self.setIconSize(QSize(18, 18))
        self.setFixedSize(46, 46)
        if tooltip:
            self.setToolTip(tooltip)
        self.setAccessibleName(tooltip or icon_name)
        self.icon_name = icon_name


class IconTextButton(QPushButton):
    def __init__(self, text: str, icon_name: str, *, parent=None) -> None:
        super().__init__(text, parent)
        self.setIcon(icon(icon_name))
        self.setIconSize(QSize(17, 17))
        self.icon_name = icon_name

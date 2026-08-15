"""Small, vendored SVG icon system used by the Qt desktop client."""

from .registry import ICON_NAMES, IconRegistry, icon
from .renderer import IconButton, IconTextButton

__all__ = ["ICON_NAMES", "IconButton", "IconRegistry", "IconTextButton", "icon"]

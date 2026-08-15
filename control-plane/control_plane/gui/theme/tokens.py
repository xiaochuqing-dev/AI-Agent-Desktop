"""Design tokens shared by the Qt surface and visual quality gates."""

from __future__ import annotations

COLORS = {
    "background_top_left": "#E8E9FD",
    "background_center": "#EEF2FD",
    "background_right": "#D8E9FF",
    "text_primary": "#111323",
    "text_secondary": "#606276",
    "text_muted": "#85879A",
    "blue": "#4F83FA",
    "indigo": "#6269EC",
    "purple": "#8B5CF6",
    "success": "#2B8050",
    "warning": "#A86A20",
    "error": "#A94A55",
    "telegram": "#31A9F4",
}
TYPE = {
    "welcome_title": 42,
    "page_title": 36,
    "section_title": 18,
    "card_title": 16,
    "body": 14,
    "small": 12,
    "caption": 11,
}
SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 20, "xxl": 24, "hero": 32}
RADIUS = {"window": 15, "card": 17, "button": 10, "input": 10, "chip": 11}
CONTROL_HEIGHT = {
    "primary": 50,
    "secondary": 48,
    "inline": 42,
    "compact": 30,
    "icon": 46,
    "input": 44,
}
ICON_SIZE = {"small": 14, "regular": 17, "large": 20, "hero": 24}
SHADOW = {"card_blur": 18, "strong_blur": 22, "alpha": 34}

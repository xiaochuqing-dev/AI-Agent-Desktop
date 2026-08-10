from __future__ import annotations

import os
from pathlib import Path


class TelegramClientDiscovery:
    """Read-only Telegram Desktop discovery for Windows.

    The probe never reads tdata, login state, Telegram databases or account
    sessions.  It only checks the public URI registration and executable hints.
    """

    def handler_available(self) -> bool:
        if os.name != "nt":
            return False
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT,
                r"tg\shell\open\command",
                0,
                winreg.KEY_READ,
            ) as key:
                value, _kind = winreg.QueryValueEx(key, "")
                return bool(str(value).strip())
        except (FileNotFoundError, OSError):
            return False

    def executable_hint_available(self) -> bool:
        if os.name != "nt":
            return False
        candidates: list[Path] = []
        appdata = os.environ.get("APPDATA")
        local_appdata = os.environ.get("LOCALAPPDATA")
        if appdata:
            candidates.append(Path(appdata) / "Telegram Desktop" / "Telegram.exe")
        if local_appdata:
            candidates.append(Path(local_appdata) / "Telegram Desktop" / "Telegram.exe")
        return any(path.is_file() for path in candidates)

    def available(self) -> bool:
        return self.handler_available() or self.executable_hint_available()

"""Safe, narrowly-scoped transactions for Hermes' public ``.env`` file.

The adapter deliberately does not use a dotenv package here.  Hermes users often
keep comments, ordering, and unknown integration keys in this file; a small
lossless line editor lets us change only the two Telegram keys owned by this
product while retaining the rest of the file verbatim.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

WRITABLE_TELEGRAM_KEY_ORDER = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS")
WRITABLE_TELEGRAM_KEYS = frozenset(WRITABLE_TELEGRAM_KEY_ORDER)
INSPECTABLE_TELEGRAM_KEYS = frozenset(
    {
        *WRITABLE_TELEGRAM_KEYS,
        "TELEGRAM_GROUP_ALLOWED_USERS",
        "TELEGRAM_GROUP_ALLOWED_CHATS",
        "TELEGRAM_HOME_CHANNEL",
    }
)
_KEY_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
_ID_RE = re.compile(r"^[0-9]+$")


class HermesEnvError(RuntimeError):
    """User-facing error raised without exposing file contents or secrets."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class HermesEnvSnapshot:
    path: Path
    values: dict[str, str] = field(repr=False)
    raw: bytes = field(repr=False)
    mode: int | None = None

    @property
    def token(self) -> str | None:
        value = self.values.get("TELEGRAM_BOT_TOKEN", "").strip()
        return value or None

    @property
    def allowed_users(self) -> tuple[str, ...]:
        return tuple(parse_allowed_users(self.values.get("TELEGRAM_ALLOWED_USERS", "")))


@dataclass(frozen=True)
class HermesEnvReceipt:
    """In-memory rollback material; never persisted or serialized to an operation."""

    path: Path
    previous_raw: bytes = field(repr=False)
    previous_mode: int | None = field(default=None, repr=False)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value.strip()


def _parse_lines(raw: bytes) -> tuple[list[str], dict[str, str]]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HermesEnvError(
            "HERMES_ENV_INVALID_ENCODING", "Hermes Telegram 配置文件不是有效的 UTF-8。"
        ) from None
    lines = text.splitlines(keepends=True)
    values: dict[str, str] = {}
    for line in lines:
        match = _KEY_RE.match(line.rstrip("\r\n"))
        if not match:
            continue
        key, value = match.groups()
        # A trailing unquoted comment is not part of a dotenv value.  Quoted
        # values are kept intact because a token can contain '#'.
        if value and value[0] not in {'"', "'"}:
            value = value.split(" #", 1)[0]
        values[key] = _unquote(value)
    return lines, values


def parse_allowed_users(value: str | None) -> list[str]:
    """Return stable, numeric, de-duplicated Telegram user IDs."""

    result: list[str] = []
    seen: set[str] = set()
    for raw in (value or "").split(","):
        item = raw.strip()
        if not item or not _ID_RE.fullmatch(item) or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def merge_allowed_users(existing: str | None, operator_user_id: int | str) -> str:
    operator = str(operator_user_id).strip()
    if not _ID_RE.fullmatch(operator):
        raise HermesEnvError("HERMES_OPERATOR_ID_INVALID", "Telegram 操作用户 ID 无效。")
    users = parse_allowed_users(existing)
    if operator not in users:
        users.append(operator)
    return ",".join(users)


class HermesEnvTransaction:
    """Read and atomically update only Hermes' public Telegram env keys."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _validate_target(self) -> None:
        if self.path.is_symlink():
            raise HermesEnvError(
                "HERMES_ENV_SYMLINK_UNSUPPORTED", "Hermes 配置文件是符号链接，未执行修改。"
            )
        if not self.path.parent.exists():
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                raise HermesEnvError(
                    "HERMES_ENV_PERMISSION_DENIED", "无法创建 Hermes 配置目录。"
                ) from None
        if not self.path.parent.is_dir():
            raise HermesEnvError("HERMES_ENV_PATH_INVALID", "Hermes 配置路径不是目录。")
        if self.path.exists() and not self.path.is_file():
            raise HermesEnvError("HERMES_ENV_PATH_INVALID", "Hermes 配置路径不是文件。")

    def inspect(self) -> HermesEnvSnapshot:
        self._validate_target()
        try:
            raw = self.path.read_bytes() if self.path.exists() else b""
            mode = stat.S_IMODE(self.path.stat().st_mode) if self.path.exists() else None
        except OSError:
            raise HermesEnvError(
                "HERMES_ENV_PERMISSION_DENIED", "无法读取 Hermes Telegram 配置文件。"
            ) from None
        _, values = _parse_lines(raw)
        filtered = {key: values[key] for key in INSPECTABLE_TELEGRAM_KEYS if key in values}
        return HermesEnvSnapshot(self.path, filtered, raw, mode)

    def update(self, *, token: str, operator_user_id: int | str) -> HermesEnvReceipt:
        if not token or "\x00" in token:
            raise HermesEnvError("HERMES_TOKEN_INVALID", "Hermes Telegram Bot Token 无效。")
        snapshot = self.inspect()
        if snapshot.mode is not None and not (snapshot.mode & 0o222):
            raise HermesEnvError(
                "HERMES_ENV_PERMISSION_DENIED",
                "Hermes Telegram 配置文件不可写，未执行修改。",
            )
        lines, _ = _parse_lines(snapshot.raw)
        target_values = {
            "TELEGRAM_BOT_TOKEN": token,
            "TELEGRAM_ALLOWED_USERS": merge_allowed_users(
                snapshot.values.get("TELEGRAM_ALLOWED_USERS", ""), operator_user_id
            ),
        }
        output: list[str] = []
        seen: set[str] = set()
        for line in lines:
            match = _KEY_RE.match(line.rstrip("\r\n"))
            if not match or match.group(1) not in WRITABLE_TELEGRAM_KEYS:
                output.append(line)
                continue
            key = match.group(1)
            if key in seen:
                continue
            seen.add(key)
            newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            output.append(f"{key}={target_values[key]}{newline}")
        newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
        for key in WRITABLE_TELEGRAM_KEY_ORDER:
            if key not in seen:
                if output and not output[-1].endswith(("\n", "\r")):
                    output.append(newline)
                output.append(f"{key}={target_values[key]}{newline}")
        new_raw = "".join(output).encode("utf-8")
        self._atomic_replace(new_raw, snapshot.mode)
        return HermesEnvReceipt(self.path, snapshot.raw, snapshot.mode)

    def rollback(self, receipt: HermesEnvReceipt) -> None:
        if receipt.path != self.path:
            raise HermesEnvError("HERMES_ROLLBACK_TARGET_MISMATCH", "Hermes 回滚目标不匹配。")
        self._atomic_replace(receipt.previous_raw, receipt.previous_mode)

    def _atomic_replace(self, raw: bytes, mode: int | None) -> None:
        self._validate_target()
        temp_path: Path | None = None
        try:
            fd, name = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
            )
            temp_path = Path(name)
            with os.fdopen(fd, "wb") as handle:
                if mode is not None:
                    os.chmod(temp_path, mode)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            temp_path = None
            try:
                directory_fd = os.open(self.path.parent, os.O_RDONLY)
            except OSError:
                directory_fd = None
            if directory_fd is not None:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    pass
                finally:
                    os.close(directory_fd)
        except HermesEnvError:
            raise
        except OSError:
            raise HermesEnvError(
                "HERMES_ENV_WRITE_FAILED", "无法安全写入 Hermes Telegram 配置。"
            ) from None
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..installer.artifacts import InstallerError
from ..installer.paths import ComponentLayout
from .native_config_models import ManagedCcConnectState

RUNTIME_RELATIVE_PATH: Literal["state/runtime-config/cc-connect.toml"] = (
    "state/runtime-config/cc-connect.toml"
)
MANAGED_RELATIVE_PATH: Literal["state/managed/cc-connect-state.json"] = (
    "state/managed/cc-connect-state.json"
)


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def managed_state_bytes(state: ManagedCcConnectState) -> bytes:
    payload = json.dumps(
        state.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    return (payload + "\n").encode("utf-8")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise InstallerError(
            "NATIVE_CONFIGURATION_ATOMIC_WRITE_FAILED",
            "cc-connect native configuration could not be committed atomically.",
            retryable=True,
            recovery_actions=["close_file_handles", "retry_native_configuration_apply"],
            technical_details={"error": type(exc).__name__},
        ) from None


@dataclass(frozen=True)
class NativeConfigCommit:
    runtime_digest: str
    managed_digest: str
    backup_runtime_relative_path: str | None
    backup_managed_relative_path: str | None
    backup_runtime_digest: str | None
    backup_managed_digest: str | None


class CcConnectNativeConfigStore:
    def __init__(self, layout: ComponentLayout) -> None:
        self.layout = layout
        self.runtime_path = layout.from_relative(RUNTIME_RELATIVE_PATH)
        self.managed_path = layout.from_relative(MANAGED_RELATIVE_PATH)

    def read_runtime(self) -> bytes | None:
        return self._read(self.runtime_path)

    def read_managed(self) -> bytes | None:
        return self._read(self.managed_path)

    def commit(
        self,
        *,
        operation_id: str,
        runtime_data: bytes,
        managed_state: ManagedCcConnectState,
    ) -> NativeConfigCommit:
        self.layout.ensure()
        previous_runtime = self.read_runtime()
        previous_managed = self.read_managed()
        backup_runtime: Path | None = None
        backup_managed: Path | None = None
        backup_root = self.layout.backup_dir(operation_id) / "native-config"
        if previous_runtime is not None:
            backup_runtime = backup_root / "cc-connect.toml"
            _atomic_write(backup_runtime, previous_runtime)
        if previous_managed is not None:
            backup_managed = backup_root / "cc-connect-state.json"
            _atomic_write(backup_managed, previous_managed)
        managed_data = managed_state_bytes(managed_state)
        try:
            _atomic_write(self.runtime_path, runtime_data)
            _atomic_write(self.managed_path, managed_data)
        except InstallerError:
            self._restore(self.runtime_path, previous_runtime)
            self._restore(self.managed_path, previous_managed)
            raise
        return NativeConfigCommit(
            runtime_digest=digest_bytes(runtime_data),
            managed_digest=digest_bytes(managed_data),
            backup_runtime_relative_path=(
                self.layout.relative(backup_runtime) if backup_runtime is not None else None
            ),
            backup_managed_relative_path=(
                self.layout.relative(backup_managed) if backup_managed is not None else None
            ),
            backup_runtime_digest=(
                digest_bytes(previous_runtime) if previous_runtime is not None else None
            ),
            backup_managed_digest=(
                digest_bytes(previous_managed) if previous_managed is not None else None
            ),
        )

    @staticmethod
    def _read(path: Path) -> bytes | None:
        try:
            return path.read_bytes() if path.exists() else None
        except OSError as exc:
            raise InstallerError(
                "NATIVE_CONFIGURATION_READ_FAILED",
                "cc-connect native configuration could not be read.",
                recovery_actions=["inspect_product_managed_state"],
                technical_details={"error": type(exc).__name__},
            ) from None

    @staticmethod
    def _restore(path: Path, previous: bytes | None) -> None:
        try:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                _atomic_write(path, previous)
        except (OSError, InstallerError) as exc:
            raise InstallerError(
                "NATIVE_CONFIGURATION_ROLLBACK_FAILED",
                "Native configuration apply failed and the previous files could not be restored.",
                recovery_actions=["stop_managed_runtime", "restore_native_configuration_backup"],
                technical_details={"error": type(exc).__name__},
            ) from None

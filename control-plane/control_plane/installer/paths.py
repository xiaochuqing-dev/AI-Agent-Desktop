from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .artifacts import InstallerError, sha256_file

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


def _validate_id(value: str, kind: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise InstallerError(
            "PATH_IDENTIFIER_INVALID",
            f"{kind} contains unsupported path characters.",
            recovery_actions=["use_locked_identifier"],
        )
    return value


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
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
            "ATOMIC_WRITE_FAILED",
            "Product state could not be committed atomically.",
            retryable=True,
            recovery_actions=["close_file_handles", "retry_operation"],
            technical_details={"error": type(exc).__name__},
        ) from None


class ComponentLayout:
    def __init__(self, components_dir: str) -> None:
        self.root = Path(components_dir) / "cc-connect"
        self.versions = self.root / "versions"
        self.staging = self.root / "staging"
        self.backups = self.root / "backups"
        self.state = self.root / "state"
        self.current_file = self.root / "current.json"

    @staticmethod
    def _is_link(path: Path) -> bool:
        is_junction = getattr(path, "is_junction", lambda: False)
        return path.is_symlink() or bool(is_junction())

    def assert_safe(self) -> None:
        managed_paths = (self.root, self.versions, self.staging, self.backups, self.state)
        if any(path.exists() and self._is_link(path) for path in managed_paths):
            raise InstallerError(
                "INSTALL_ROOT_UNSAFE",
                "Product component paths cannot be symbolic links or junctions.",
                recovery_actions=["restore_product_data_directory"],
            )
        if self.current_file.exists() and self._is_link(self.current_file):
            raise InstallerError(
                "CURRENT_POINTER_UNSAFE",
                "Product current pointer cannot be a symbolic link or junction.",
                recovery_actions=["restore_product_data_directory"],
            )

    def ensure(self) -> None:
        self.assert_safe()
        for directory in (self.versions, self.staging, self.backups, self.state):
            directory.mkdir(parents=True, exist_ok=True)
        self.assert_safe()

    def version_dir(self, artifact_id: str) -> Path:
        return self._child(self.versions, _validate_id(artifact_id, "artifact_id"))

    def staging_dir(self, operation_id: str) -> Path:
        return self._child(self.staging, _validate_id(operation_id, "operation_id"))

    def backup_dir(self, operation_id: str) -> Path:
        return self._child(self.backups, _validate_id(operation_id, "operation_id"))

    def _child(self, parent: Path, name: str) -> Path:
        self.assert_safe()
        target = parent / name
        parent_resolved = parent.resolve(strict=False)
        target_resolved = target.resolve(strict=False)
        if not target_resolved.is_relative_to(parent_resolved):
            raise InstallerError(
                "PATH_TRAVERSAL_BLOCKED",
                "Resolved path escaped the product component root.",
                recovery_actions=["use_locked_identifier"],
            )
        self._assert_no_link_components(target)
        return target

    def relative(self, path: Path) -> str:
        self.assert_safe()
        resolved = path.resolve(strict=False)
        root = self.root.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise InstallerError(
                "PATH_TRAVERSAL_BLOCKED",
                "Path is outside the product component root.",
                recovery_actions=["use_product_managed_path"],
            )
        return resolved.relative_to(root).as_posix()

    def from_relative(self, relative_path: str) -> Path:
        self.assert_safe()
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise InstallerError(
                "PATH_TRAVERSAL_BLOCKED",
                "Persisted cleanup path is not product-relative.",
                recovery_actions=["inspect_pending_cleanup"],
            )
        return self._child_path(candidate)

    def _child_path(self, candidate: Path) -> Path:
        target = self.root / candidate
        if not target.resolve(strict=False).is_relative_to(self.root.resolve(strict=False)):
            raise InstallerError(
                "PATH_TRAVERSAL_BLOCKED",
                "Path escaped the product component root.",
                recovery_actions=["inspect_product_state"],
            )
        self._assert_no_link_components(target)
        return target

    def _assert_no_link_components(self, target: Path) -> None:
        root = self.root.resolve(strict=False)
        candidate = target
        while candidate != self.root and candidate != candidate.parent:
            if candidate.exists() and self._is_link(candidate):
                raise InstallerError(
                    "INSTALL_PATH_UNSAFE",
                    "Product-managed path contains a symbolic link or junction.",
                    recovery_actions=["inspect_product_state"],
                )
            candidate = candidate.parent
        if not target.resolve(strict=False).is_relative_to(root):
            raise InstallerError(
                "PATH_TRAVERSAL_BLOCKED",
                "Path escaped the product component root.",
                recovery_actions=["inspect_product_state"],
            )

    def read_current(self) -> dict[str, Any] | None:
        self.assert_safe()
        if not self.current_file.exists():
            return None
        try:
            payload = json.loads(self.current_file.read_text(encoding="utf-8-sig"))
            artifact_id = payload["artifact_id"]
            _validate_id(artifact_id, "artifact_id")
            version = payload["version"]
            digest = payload["artifact_sha256"]
            previous = payload.get("previous_artifact_id")
            if (
                payload.get("schema_version") != "1.0"
                or not isinstance(version, str)
                or not version
                or not isinstance(digest, str)
                or not _SHA256.fullmatch(digest)
                or (previous is not None and not isinstance(previous, str))
            ):
                raise ValueError
            if previous is not None:
                _validate_id(previous, "previous_artifact_id")
            return payload
        except (InstallerError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            raise InstallerError(
                "CURRENT_POINTER_INVALID",
                "Product current pointer is unreadable or invalid.",
                recovery_actions=["restore_previous_product_version"],
            ) from None

    def write_current(self, payload: dict[str, Any]) -> None:
        self.assert_safe()
        _validate_id(str(payload.get("artifact_id", "")), "artifact_id")
        digest = payload.get("artifact_sha256")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise InstallerError(
                "CURRENT_POINTER_INVALID",
                "Product current pointer digest is invalid.",
                recovery_actions=["restore_previous_product_version"],
            )
        atomic_write_json(self.current_file, payload)

    def restore_current(self, payload: dict[str, Any] | None) -> None:
        self.assert_safe()
        if payload is None:
            try:
                self.current_file.unlink(missing_ok=True)
            except OSError as exc:
                raise InstallerError(
                    "ROLLBACK_CURRENT_FAILED",
                    "Previous empty current state could not be restored.",
                    recovery_actions=["close_file_handles", "remove_current_pointer_manually"],
                    technical_details={"error": type(exc).__name__},
                ) from None
            return
        self.write_current(payload)

    def directory_digest(self) -> str:
        self.assert_safe()
        digest = hashlib.sha256()
        if not self.root.exists():
            return digest.hexdigest()
        if any(self._is_link(item) for item in self.root.rglob("*")):
            raise InstallerError(
                "INSTALL_PATH_UNSAFE",
                "Product-managed directory contains a symbolic link or junction.",
                recovery_actions=["inspect_product_state"],
            )
        for path in sorted(
            (item for item in self.root.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(self.root).as_posix(),
        ):
            relative = path.relative_to(self.root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(sha256_file(path).encode("ascii"))
            digest.update(b"\n")
        return digest.hexdigest()

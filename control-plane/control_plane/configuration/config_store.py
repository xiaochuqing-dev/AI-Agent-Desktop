from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from ..installer.artifacts import InstallerError
from ..installer.paths import ComponentLayout
from .models import ManagedConfiguration
from .templates import parse_managed_toml, render_managed_toml

CONFIG_RELATIVE_PATH: Literal["state/config/cc-connect.managed.toml"] = (
    "state/config/cc-connect.managed.toml"
)


def configuration_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class ConfigurationError(InstallerError):
    pass


@dataclass(frozen=True)
class ConfigurationCommit:
    configuration: ManagedConfiguration
    digest: str
    relative_path: str
    backup_relative_path: str | None
    backup_digest: str | None
    previous_bytes: bytes | None


class ConfigurationStore:
    def __init__(
        self,
        layout: ComponentLayout,
        *,
        post_write_validator: Callable[[bytes], ManagedConfiguration] | None = None,
    ) -> None:
        self.layout = layout
        self.post_write_validator = post_write_validator or parse_managed_toml

    @property
    def path(self) -> Path:
        return self.layout.from_relative(CONFIG_RELATIVE_PATH)

    def exists(self) -> bool:
        self._assert_safe()
        return self.path.is_file()

    def read_bytes(self) -> bytes | None:
        self._assert_safe()
        try:
            return self.path.read_bytes() if self.path.exists() else None
        except PermissionError:
            raise ConfigurationError(
                "CONFIGURATION_FILE_INACCESSIBLE",
                "The product-managed configuration cannot be read with current-user permissions.",
                recovery_actions=["close_file_handles", "restore_product_directory_permissions"],
            ) from None
        except OSError as exc:
            raise ConfigurationError(
                "CONFIGURATION_READ_FAILED",
                "The product-managed configuration could not be read.",
                retryable=True,
                recovery_actions=["inspect_product_state"],
                technical_details={"error": type(exc).__name__},
            ) from None

    def read(self) -> ManagedConfiguration | None:
        data = self.read_bytes()
        if data is None:
            return None
        try:
            return parse_managed_toml(data)
        except (UnicodeDecodeError, ValueError, ValidationError) as exc:
            raise ConfigurationError(
                "CONFIGURATION_INVALID",
                "The product-managed configuration failed UTF-8, TOML, or schema validation.",
                recovery_actions=["create_configuration_rollback_plan"],
                technical_details={"error": type(exc).__name__},
            ) from None

    def digest(self) -> str | None:
        data = self.read_bytes()
        return configuration_digest(data) if data is not None else None

    def commit(
        self,
        configuration: ManagedConfiguration,
        *,
        operation_id: str,
        expected_current_digest: str | None,
    ) -> ConfigurationCommit:
        self.layout.ensure()
        self._assert_safe()
        rendered = render_managed_toml(configuration)
        try:
            reparsed = parse_managed_toml(rendered)
        except (UnicodeDecodeError, ValueError, ValidationError) as exc:
            raise ConfigurationError(
                "CONFIGURATION_TEMPLATE_INVALID",
                "Generated configuration failed validation before writing.",
                recovery_actions=["inspect_configuration_template"],
                technical_details={"error": type(exc).__name__},
            ) from None
        if reparsed != configuration:
            raise ConfigurationError(
                "CONFIGURATION_TEMPLATE_ROUNDTRIP_FAILED",
                "Generated configuration changed during TOML round-trip validation.",
                recovery_actions=["inspect_configuration_template"],
            )
        previous = self.read_bytes()
        actual_digest = configuration_digest(previous) if previous is not None else None
        if actual_digest != expected_current_digest:
            raise ConfigurationError(
                "CONFIGURATION_REVISION_CONFLICT",
                "Configuration changed after planning; no file was written.",
                retryable=True,
                recovery_actions=["create_new_configuration_plan"],
            )
        backup_path: Path | None = None
        backup_digest: str | None = None
        if previous is not None:
            backup_path = self.layout.backup_dir(operation_id) / (
                f"configuration-r{configuration.configuration_revision - 1}.toml"
            )
            self._atomic_write(backup_path, previous, purpose="backup")
            backup_digest = configuration_digest(previous)
        replaced = False
        try:
            self._atomic_write(self.path, rendered, purpose="configuration")
            replaced = True
            persisted = self.path.read_bytes()
            validated = self.post_write_validator(persisted)
            if validated != configuration:
                raise ConfigurationError(
                    "CONFIGURATION_POST_WRITE_MISMATCH",
                    "Persisted configuration does not match the confirmed plan.",
                    recovery_actions=["automatic_configuration_rollback"],
                )
        except ConfigurationError:
            if replaced:
                self._restore_previous(previous)
            raise
        except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
            if replaced:
                try:
                    self._restore_previous(previous)
                except ConfigurationError as rollback_error:
                    raise ConfigurationError(
                        "CONFIGURATION_ROLLBACK_FAILED",
                        "Configuration write failed and the previous bytes could not be restored.",
                        recovery_actions=["inspect_pending_repair"],
                        technical_details={
                            "write_error": type(exc).__name__,
                            "rollback_error": rollback_error.code,
                        },
                    ) from None
            raise ConfigurationError(
                "CONFIGURATION_POST_WRITE_VALIDATION_FAILED",
                "Configuration was restored after post-write validation failed.",
                recovery_actions=["create_new_configuration_plan"],
                technical_details={"error": type(exc).__name__},
            ) from None
        return ConfigurationCommit(
            configuration=configuration,
            digest=configuration_digest(rendered),
            relative_path=CONFIG_RELATIVE_PATH,
            backup_relative_path=(self.layout.relative(backup_path) if backup_path else None),
            backup_digest=backup_digest,
            previous_bytes=previous,
        )

    def restore_commit(self, commit: ConfigurationCommit) -> None:
        self._restore_previous(commit.previous_bytes)

    def _restore_previous(self, previous: bytes | None) -> None:
        if previous is None:
            try:
                self.path.unlink(missing_ok=True)
            except OSError as exc:
                raise ConfigurationError(
                    "CONFIGURATION_ROLLBACK_FAILED",
                    "New configuration could not be removed during rollback.",
                    recovery_actions=["inspect_pending_repair"],
                    technical_details={"error": type(exc).__name__},
                ) from None
            return
        self._atomic_write(self.path, previous, purpose="rollback")

    def _atomic_write(self, path: Path, data: bytes, *, purpose: str) -> None:
        self._assert_safe()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._assert_safe()
        if not os.access(path.parent, os.W_OK):
            raise ConfigurationError(
                "CONFIGURATION_PERMISSION_DENIED",
                f"Current user cannot write the product-managed {purpose} directory.",
                recovery_actions=["restore_product_directory_permissions"],
            )
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
        except PermissionError:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise ConfigurationError(
                "CONFIGURATION_FILE_LOCKED",
                f"The product-managed {purpose} file is locked or not replaceable.",
                retryable=True,
                recovery_actions=["close_file_handles", "retry_operation"],
            ) from None
        except OSError as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise ConfigurationError(
                "CONFIGURATION_ATOMIC_WRITE_FAILED",
                f"The product-managed {purpose} could not be replaced atomically.",
                retryable=True,
                recovery_actions=["inspect_product_state", "retry_operation"],
                technical_details={"error": type(exc).__name__},
            ) from None

    def _assert_safe(self) -> None:
        self.layout.assert_safe()
        target = self.layout.from_relative(CONFIG_RELATIVE_PATH)
        config_dir = target.parent
        is_junction = getattr(config_dir, "is_junction", lambda: False)
        if config_dir.exists() and (config_dir.is_symlink() or bool(is_junction())):
            raise ConfigurationError(
                "CONFIGURATION_PATH_UNSAFE",
                "Configuration directory cannot be a symbolic link or junction.",
                recovery_actions=["restore_product_data_directory"],
            )

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Protocol

import keyring
from keyring import errors as keyring_errors

from .models import CredentialBackendCapability, CredentialStatus


class SecretBackend(Protocol):
    backend_id: str

    def probe(self) -> CredentialBackendCapability: ...

    def put(self, reference_id: str, secret: str) -> None: ...

    def replace(self, reference_id: str, secret: str) -> None: ...

    def status(self, reference_id: str) -> CredentialStatus: ...

    def resolve_for_operation(self, reference_id: str) -> AbstractContextManager[str]: ...

    def delete(self, reference_id: str) -> None: ...

    def list_metadata(self, reference_ids: Iterable[str]) -> dict[str, CredentialStatus]: ...


@dataclass(frozen=True)
class CredentialBackendError(Exception):
    code: str
    message: str
    status: CredentialStatus

    def __str__(self) -> str:
        return self.message


class WindowsCredentialManagerBackend:
    backend_id = "windows_credential_manager"
    service_name = "AI-Agent-Desktop.ControlPlane"
    _expected_backend = "keyring.backends.Windows.WinVaultKeyring"

    def __init__(self, backend=None, *, platform: str | None = None) -> None:
        self._backend = backend or keyring.get_keyring()
        self._platform = platform or sys.platform

    def _backend_name(self) -> str:
        cls = type(self._backend)
        return f"{cls.__module__}.{cls.__name__}"

    def probe(self) -> CredentialBackendCapability:
        native = self._platform == "win32" and self._backend_name() == self._expected_backend
        status = CredentialStatus.AVAILABLE if native else CredentialStatus.BACKEND_UNAVAILABLE
        if native:
            try:
                self._backend.get_password(self.service_name, "__capability_probe_missing__")
            except Exception as exc:  # backend boundary: map without echoing values
                status = self._map_exception(exc).status
        return CredentialBackendCapability(
            backend_id="windows_credential_manager",
            status=status,
            native_windows_backend=native,
            supports_put=native,
            supports_replace=native,
            supports_status=native,
            supports_resolve_for_operation=native,
            supports_delete=native,
            supports_list_metadata=native,
            evidence={
                "backend_class": self._backend_name(),
                "expected_backend_class": self._expected_backend,
                "plaintext_file_fallback_allowed": False,
            },
        )

    def _require_available(self) -> None:
        capability = self.probe()
        if capability.status != CredentialStatus.AVAILABLE:
            raise CredentialBackendError(
                "CREDENTIAL_BACKEND_UNAVAILABLE",
                "Windows Credential Manager is unavailable; plaintext fallback is forbidden.",
                capability.status,
            )

    def put(self, reference_id: str, secret: str) -> None:
        self._require_available()
        if self.status(reference_id) == CredentialStatus.AVAILABLE:
            raise CredentialBackendError(
                "CREDENTIAL_ALREADY_EXISTS",
                "Credential already exists and requires an explicit replace operation.",
                CredentialStatus.AVAILABLE,
            )
        self._set(reference_id, secret)

    def replace(self, reference_id: str, secret: str) -> None:
        self._require_available()
        self._set(reference_id, secret)

    def _set(self, reference_id: str, secret: str) -> None:
        try:
            self._backend.set_password(self.service_name, reference_id, secret)
        except Exception as exc:
            raise self._map_exception(exc) from None
        if self.status(reference_id) != CredentialStatus.AVAILABLE:
            raise CredentialBackendError(
                "CREDENTIAL_WRITE_NOT_CONFIRMED",
                "Credential write could not be confirmed by the native backend.",
                CredentialStatus.UNKNOWN,
            )

    def status(self, reference_id: str) -> CredentialStatus:
        capability = self.probe()
        if capability.status != CredentialStatus.AVAILABLE:
            return capability.status
        try:
            value = self._backend.get_password(self.service_name, reference_id)
        except Exception as exc:
            return self._map_exception(exc).status
        if value is None:
            return CredentialStatus.MISSING
        if not isinstance(value, str) or not value:
            return CredentialStatus.CORRUPT
        return CredentialStatus.AVAILABLE

    @contextmanager
    def resolve_for_operation(self, reference_id: str) -> Iterator[str]:
        self._require_available()
        try:
            value = self._backend.get_password(self.service_name, reference_id)
        except Exception as exc:
            raise self._map_exception(exc) from None
        if value is None:
            raise CredentialBackendError(
                "CREDENTIAL_MISSING",
                "Required credential is missing.",
                CredentialStatus.MISSING,
            )
        if not isinstance(value, str) or not value:
            raise CredentialBackendError(
                "CREDENTIAL_CORRUPT",
                "Credential could not be decoded by the native backend.",
                CredentialStatus.CORRUPT,
            )
        try:
            yield value
        finally:
            # Python/keyring use immutable strings, so physical zeroing cannot be guaranteed.
            value = ""

    def delete(self, reference_id: str) -> None:
        self._require_available()
        try:
            self._backend.delete_password(self.service_name, reference_id)
        except keyring_errors.PasswordDeleteError:
            return
        except Exception as exc:
            raise self._map_exception(exc) from None

    def list_metadata(self, reference_ids: Iterable[str]) -> dict[str, CredentialStatus]:
        return {reference_id: self.status(reference_id) for reference_id in reference_ids}

    @staticmethod
    def _map_exception(exc: Exception) -> CredentialBackendError:
        if isinstance(exc, PermissionError):
            return CredentialBackendError(
                "CREDENTIAL_PERMISSION_DENIED",
                "Windows Credential Manager denied access for the current user.",
                CredentialStatus.INACCESSIBLE,
            )
        if isinstance(exc, (keyring_errors.NoKeyringError, keyring_errors.InitError)):
            return CredentialBackendError(
                "CREDENTIAL_BACKEND_UNAVAILABLE",
                "Windows Credential Manager backend is unavailable.",
                CredentialStatus.BACKEND_UNAVAILABLE,
            )
        if isinstance(exc, UnicodeError):
            return CredentialBackendError(
                "CREDENTIAL_CORRUPT",
                "Credential could not be decoded by the native backend.",
                CredentialStatus.CORRUPT,
            )
        return CredentialBackendError(
            "CREDENTIAL_BACKEND_ERROR",
            f"Credential backend operation failed: {type(exc).__name__}.",
            CredentialStatus.UNKNOWN,
        )


class InMemorySecretBackend:
    backend_id = "memory"

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self.forced_status: dict[str, CredentialStatus] = {}

    def probe(self) -> CredentialBackendCapability:
        return CredentialBackendCapability(
            backend_id="memory",
            status=CredentialStatus.AVAILABLE,
            native_windows_backend=False,
            supports_put=True,
            supports_replace=True,
            supports_status=True,
            supports_resolve_for_operation=True,
            supports_delete=True,
            supports_list_metadata=True,
            evidence={"test_only": True, "plaintext_file_fallback_allowed": False},
        )

    def put(self, reference_id: str, secret: str) -> None:
        if reference_id in self._values:
            raise CredentialBackendError(
                "CREDENTIAL_ALREADY_EXISTS",
                "Credential already exists and requires replacement.",
                CredentialStatus.AVAILABLE,
            )
        self._values[reference_id] = secret

    def replace(self, reference_id: str, secret: str) -> None:
        self._values[reference_id] = secret

    def status(self, reference_id: str) -> CredentialStatus:
        if reference_id in self.forced_status:
            return self.forced_status[reference_id]
        return (
            CredentialStatus.AVAILABLE if reference_id in self._values else CredentialStatus.MISSING
        )

    @contextmanager
    def resolve_for_operation(self, reference_id: str) -> Iterator[str]:
        status = self.status(reference_id)
        if status != CredentialStatus.AVAILABLE:
            raise CredentialBackendError(
                "CREDENTIAL_NOT_AVAILABLE",
                "Credential is not available for the operation.",
                status,
            )
        value = self._values[reference_id]
        try:
            yield value
        finally:
            value = ""

    def delete(self, reference_id: str) -> None:
        self._values.pop(reference_id, None)

    def list_metadata(self, reference_ids: Iterable[str]) -> dict[str, CredentialStatus]:
        return {reference_id: self.status(reference_id) for reference_id in reference_ids}

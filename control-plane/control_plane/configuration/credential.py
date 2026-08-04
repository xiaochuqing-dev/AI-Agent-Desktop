from __future__ import annotations

from typing import Protocol

from .models import SecretReference, SecretStatus


class CredentialBackend(Protocol):
    backend_id: str

    def status(self, reference: SecretReference) -> SecretStatus: ...


class InMemoryCredentialBackend:
    """Test backend that stores status only and can never hold a credential value."""

    backend_id = "memory"

    def __init__(self, statuses: dict[str, SecretStatus] | None = None) -> None:
        self._statuses = dict(statuses or {})

    def set_status(self, reference_id: str, status: SecretStatus) -> None:
        self._statuses[reference_id] = status

    def status(self, reference: SecretReference) -> SecretStatus:
        return self._statuses.get(reference.reference_id, SecretStatus.MISSING)


class WindowsCredentialManagerBackend:
    """Boundary scaffold; this slice intentionally never reads or writes real credentials."""

    backend_id = "windows_credential_manager"

    def status(self, _reference: SecretReference) -> SecretStatus:
        return SecretStatus.UNKNOWN

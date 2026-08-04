from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Literal, cast

from ..persistence.models import CredentialReferenceRecord, CredentialRevisionRecord
from ..persistence.session import Database
from .models import (
    INTERNAL_BINDING_HMAC_REFERENCE,
    INTERNAL_CC_CONNECT_MANAGEMENT_REFERENCE,
    PUBLIC_CREDENTIAL_REFERENCES,
    CredentialMetadata,
    CredentialPurpose,
    CredentialStatus,
    purpose_for_reference,
)
from .windows_backend import SecretBackend, WindowsCredentialManagerBackend


def utcnow() -> datetime:
    return datetime.now(UTC)


class CredentialService:
    def __init__(self, database: Database, backend: SecretBackend | None = None) -> None:
        self.db = database
        self.backend = backend or WindowsCredentialManagerBackend()

    def capability(self):
        return self.backend.probe()

    def put(self, reference_id: str, secret: str, *, operation_id: str) -> CredentialMetadata:
        purpose = purpose_for_reference(reference_id)
        self.backend.put(reference_id, secret)
        return self._record_revision(
            reference_id, purpose.value, operation_id, CredentialStatus.AVAILABLE
        )

    def replace(self, reference_id: str, secret: str, *, operation_id: str) -> CredentialMetadata:
        purpose = purpose_for_reference(reference_id)
        self.backend.replace(reference_id, secret)
        return self._record_revision(
            reference_id, purpose.value, operation_id, CredentialStatus.AVAILABLE
        )

    def delete(self, reference_id: str, *, operation_id: str) -> CredentialMetadata:
        purpose = purpose_for_reference(reference_id)
        self.backend.delete(reference_id)
        return self._record_revision(
            reference_id, purpose.value, operation_id, CredentialStatus.MISSING
        )

    def get(self, reference_id: str) -> CredentialMetadata:
        purpose = purpose_for_reference(reference_id)
        status = self.backend.status(reference_id)
        with self.db.session() as session:
            record = session.get(CredentialReferenceRecord, reference_id)
            if record is None:
                return CredentialMetadata(
                    reference_id=reference_id,
                    purpose=purpose,
                    backend=self.backend.backend_id,  # type: ignore[arg-type]
                    revision=0,
                    status=status,
                )
            record.status = status.value
            record.updated_at = utcnow()
            return self._metadata(record)

    def list_metadata(self, *, include_internal: bool = False) -> list[CredentialMetadata]:
        references = [value[0] for value in PUBLIC_CREDENTIAL_REFERENCES.values()]
        if include_internal:
            references.extend(
                [INTERNAL_CC_CONNECT_MANAGEMENT_REFERENCE, INTERNAL_BINDING_HMAC_REFERENCE]
            )
        return [self.get(reference_id) for reference_id in references]

    @contextmanager
    def resolve_for_operation(self, reference_id: str) -> Iterator[str]:
        with self.backend.resolve_for_operation(reference_id) as value:
            yield value

    def mark_verified(self, reference_id: str, revision: int, verified_at: datetime) -> None:
        with self.db.session() as session:
            record = session.get(CredentialReferenceRecord, reference_id)
            if record is not None and record.revision == revision:
                record.verified_at = verified_at
                record.updated_at = utcnow()

    def ensure_internal_runtime_credentials(self) -> None:
        for reference_id, size in (
            (INTERNAL_CC_CONNECT_MANAGEMENT_REFERENCE, 32),
            (INTERNAL_BINDING_HMAC_REFERENCE, 48),
        ):
            if self.backend.status(reference_id) == CredentialStatus.MISSING:
                self.backend.put(reference_id, secrets.token_urlsafe(size))
                purpose = purpose_for_reference(reference_id)
                self._record_revision(
                    reference_id,
                    purpose.value,
                    "internal-bootstrap",
                    CredentialStatus.AVAILABLE,
                )

    def _record_revision(
        self,
        reference_id: str,
        purpose: str,
        operation_id: str,
        status: CredentialStatus,
    ) -> CredentialMetadata:
        now = utcnow()
        with self.db.session() as session:
            record = session.get(CredentialReferenceRecord, reference_id)
            revision = (record.revision if record else 0) + 1
            if record is None:
                record = CredentialReferenceRecord(
                    reference_id=reference_id,
                    purpose=purpose,
                    backend=self.backend.backend_id,
                    revision=revision,
                    status=status.value,
                    verified_at=None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            else:
                record.purpose = purpose
                record.backend = self.backend.backend_id
                record.revision = revision
                record.status = status.value
                record.verified_at = None
                record.updated_at = now
            session.add(
                CredentialRevisionRecord(
                    reference_id=reference_id,
                    revision=revision,
                    operation_id=operation_id,
                    status=status.value,
                    created_at=now,
                )
            )
            session.flush()
            return self._metadata(record)

    @staticmethod
    def _metadata(record: CredentialReferenceRecord) -> CredentialMetadata:
        return CredentialMetadata(
            reference_id=record.reference_id,
            purpose=CredentialPurpose(record.purpose),
            backend=cast(Literal["windows_credential_manager", "memory"], record.backend),
            revision=record.revision,
            status=CredentialStatus(record.status),
            verified_at=record.verified_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from ..operations import OperationExecutionError
from ..persistence.models import TelegramUpdateLeaseRecord
from ..persistence.session import Database
from .models import TelegramBotSlot, TelegramUpdateLease, UpdateOwner


def utcnow() -> datetime:
    return datetime.now(UTC)


class TelegramUpdateLeaseService:
    def __init__(self, database: Database) -> None:
        self.db = database

    def get(self, slot: TelegramBotSlot) -> TelegramUpdateLease:
        with self.db.session() as session:
            record = session.get(TelegramUpdateLeaseRecord, slot)
            if record is None:
                return TelegramUpdateLease(bot_slot=slot, owner=UpdateOwner.NONE)
            if (
                record.owner != UpdateOwner.NONE.value
                and record.expires_at is not None
                and record.expires_at.replace(tzinfo=record.expires_at.tzinfo or UTC) <= utcnow()
            ):
                record.owner = UpdateOwner.NONE.value
                record.operation_id = None
                record.expires_at = None
                record.heartbeat_at = utcnow()
                record.release_reason = "lease_expired"
                record.revision += 1
                session.flush()
            return self._model(record)

    def acquire(
        self,
        slot: TelegramBotSlot,
        owner: UpdateOwner,
        operation_id: str,
        credential_revision: int,
        *,
        ttl_seconds: int = 60,
    ) -> TelegramUpdateLease:
        now = utcnow()
        with self.db.session() as session:
            record = session.get(TelegramUpdateLeaseRecord, slot)
            active = False
            if record is not None:
                active = bool(
                    record.owner != UpdateOwner.NONE.value
                    and record.expires_at is not None
                    and record.expires_at.replace(tzinfo=record.expires_at.tzinfo or UTC) > now
                )
            if (
                active
                and record is not None
                and (record.owner != owner.value or record.operation_id != operation_id)
            ):
                raise OperationExecutionError(
                    "TELEGRAM_UPDATE_LEASE_CONFLICT",
                    f"Telegram bot slot {slot} already has an active update owner.",
                    retryable=True,
                    recovery_actions=["wait_for_lease_release", "inspect_update_owner"],
                )
            reset_offset = record is not None and record.credential_revision != credential_revision
            revision = (record.revision if record else 0) + 1
            if record is None:
                record = TelegramUpdateLeaseRecord(
                    bot_slot=slot,
                    owner=owner.value,
                    operation_id=operation_id,
                    credential_revision=credential_revision,
                    acquired_at=now,
                    expires_at=now + timedelta(seconds=ttl_seconds),
                    heartbeat_at=now,
                    offset=0,
                    release_reason=None,
                    revision=revision,
                )
                session.add(record)
            else:
                record.owner = owner.value
                record.operation_id = operation_id
                record.credential_revision = credential_revision
                record.acquired_at = now
                record.expires_at = now + timedelta(seconds=ttl_seconds)
                record.heartbeat_at = now
                if reset_offset:
                    record.offset = 0
                record.release_reason = None
                record.revision = revision
            session.flush()
            return self._model(record)

    def heartbeat(
        self,
        slot: TelegramBotSlot,
        operation_id: str,
        *,
        next_offset: int | None = None,
        ttl_seconds: int = 60,
    ) -> TelegramUpdateLease:
        now = utcnow()
        with self.db.session() as session:
            record = session.get(TelegramUpdateLeaseRecord, slot)
            if record is None or record.operation_id != operation_id:
                raise OperationExecutionError(
                    "TELEGRAM_UPDATE_LEASE_LOST",
                    "Telegram update lease was lost during polling.",
                    retryable=True,
                    recovery_actions=["restart_binding_poll"],
                )
            if next_offset is not None and next_offset > record.offset:
                record.offset = next_offset
            record.heartbeat_at = now
            record.expires_at = now + timedelta(seconds=ttl_seconds)
            record.revision += 1
            session.flush()
            return self._model(record)

    def release(
        self, slot: TelegramBotSlot, operation_id: str | None, reason: str
    ) -> TelegramUpdateLease:
        with self.db.session() as session:
            record = session.get(TelegramUpdateLeaseRecord, slot)
            if record is None:
                record = TelegramUpdateLeaseRecord(
                    bot_slot=slot,
                    owner=UpdateOwner.NONE.value,
                    operation_id=None,
                    credential_revision=0,
                    acquired_at=None,
                    expires_at=None,
                    heartbeat_at=None,
                    offset=0,
                    release_reason=reason,
                    revision=1,
                )
                session.add(record)
            elif operation_id is None or record.operation_id == operation_id:
                record.owner = UpdateOwner.NONE.value
                record.operation_id = None
                record.expires_at = None
                record.heartbeat_at = utcnow()
                record.release_reason = reason
                record.revision += 1
            session.flush()
            return self._model(record)

    def acquire_runtime(
        self,
        slots: list[TelegramBotSlot],
        operation_id: str,
        *,
        credential_revisions: dict[str, int] | None = None,
    ) -> None:
        acquired: list[TelegramBotSlot] = []
        try:
            for slot in slots:
                lease = self.get(slot)
                credential_revision = (credential_revisions or {}).get(
                    slot
                ) or lease.credential_revision
                if credential_revision < 1:
                    raise OperationExecutionError(
                        "TELEGRAM_IDENTITY_NOT_VERIFIED",
                        f"Telegram bot slot {slot} has no verified credential revision.",
                        recovery_actions=["verify_bot_identity"],
                    )
                self.acquire(
                    slot,
                    UpdateOwner.HERMES_RUNTIME
                    if slot == "hermes"
                    else UpdateOwner.CC_CONNECT_RUNTIME,
                    operation_id,
                    credential_revision,
                    ttl_seconds=24 * 60 * 60,
                )
                acquired.append(slot)
        except Exception:
            for slot in acquired:
                self.release(slot, operation_id, "runtime_acquire_rollback")
            raise

    def release_runtime(self, slots: list[TelegramBotSlot], reason: str) -> None:
        for slot in slots:
            lease = self.get(slot)
            expected_owner = (
                UpdateOwner.HERMES_RUNTIME if slot == "hermes" else UpdateOwner.CC_CONNECT_RUNTIME
            )
            if lease.owner == expected_owner:
                self.release(slot, lease.operation_id, reason)

    @staticmethod
    def _model(record: TelegramUpdateLeaseRecord) -> TelegramUpdateLease:
        return TelegramUpdateLease(
            bot_slot=cast(TelegramBotSlot, record.bot_slot),
            owner=UpdateOwner(record.owner),
            operation_id=record.operation_id,
            credential_revision=record.credential_revision,
            acquired_at=record.acquired_at,
            expires_at=record.expires_at,
            heartbeat_at=record.heartbeat_at,
            offset=record.offset,
            release_reason=record.release_reason,
            revision=record.revision,
        )

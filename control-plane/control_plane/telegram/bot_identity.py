from __future__ import annotations

import asyncio
import builtins
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import select

from ..credentials.models import PUBLIC_CREDENTIAL_REFERENCES, CredentialStatus
from ..credentials.service import CredentialService
from ..operations import OperationExecutionError
from ..persistence.models import TelegramBotIdentityRecord
from ..persistence.session import Database
from .api_client import TelegramApiError, TelegramBotApiClient
from .models import TelegramBotIdentity, TelegramBotSlot, TelegramWebhookInfo


def utcnow() -> datetime:
    return datetime.now(UTC)


class TelegramBotIdentityService:
    def __init__(
        self,
        database: Database,
        credentials: CredentialService,
        client: TelegramBotApiClient | None = None,
    ) -> None:
        self.db = database
        self.credentials = credentials
        self.client = client or TelegramBotApiClient()

    def verify(
        self,
        slot: TelegramBotSlot,
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> TelegramBotIdentity:
        reference_id = PUBLIC_CREDENTIAL_REFERENCES[slot][0]
        metadata = self.credentials.get(reference_id)
        if metadata.status != CredentialStatus.AVAILABLE or metadata.revision < 1:
            raise OperationExecutionError(
                "CREDENTIAL_NOT_AVAILABLE",
                "Telegram bot credential is not available for verification.",
                recovery_actions=["put_or_replace_credential"],
            )
        try:
            with self.credentials.resolve_for_operation(reference_id) as token:
                payload = asyncio.run(self.client.get_me(token, cancel_event=cancel_event))
        except TelegramApiError as exc:
            raise OperationExecutionError(
                exc.code,
                exc.message,
                retryable=exc.retryable,
                recovery_actions=["replace_credential", "retry_verification"],
            ) from None
        if not bool(payload.get("is_bot")):
            raise OperationExecutionError(
                "TELEGRAM_IDENTITY_NOT_BOT",
                "Telegram getMe did not return a bot identity.",
                recovery_actions=["replace_credential"],
            )
        try:
            bot_id = int(payload["id"])
            username = str(payload["username"]).strip()
            first_name = str(payload["first_name"]).strip()
        except (KeyError, TypeError, ValueError):
            raise OperationExecutionError(
                "TELEGRAM_IDENTITY_INVALID",
                "Telegram getMe response is missing required identity fields.",
                recovery_actions=["retry_verification"],
            ) from None
        if not username or not first_name:
            raise OperationExecutionError(
                "TELEGRAM_IDENTITY_INVALID",
                "Telegram bot identity is missing username or first name.",
                recovery_actions=["retry_verification"],
            )
        verified_at = utcnow()
        identity = TelegramBotIdentity(
            slot=slot,
            bot_id=bot_id,
            username=username,
            first_name=first_name,
            can_join_groups=bool(payload.get("can_join_groups", False)),
            can_read_all_group_messages=bool(payload.get("can_read_all_group_messages", False)),
            credential_reference_id=reference_id,
            credential_revision=metadata.revision,
            verified_at=verified_at,
            verification_status="verified",
        )
        with self.db.session() as session:
            duplicate = session.scalar(
                select(TelegramBotIdentityRecord).where(
                    TelegramBotIdentityRecord.bot_id == bot_id,
                    TelegramBotIdentityRecord.slot != slot,
                )
            )
            if duplicate is not None:
                raise OperationExecutionError(
                    "TELEGRAM_BOT_IDENTITY_CONFLICT",
                    "The same Telegram bot identity cannot occupy multiple slots.",
                    recovery_actions=["replace_conflicting_credential"],
                )
            session.merge(
                TelegramBotIdentityRecord(
                    slot=slot,
                    bot_id=bot_id,
                    username=username,
                    first_name=first_name,
                    can_join_groups=1 if identity.can_join_groups else 0,
                    can_read_all_group_messages=(1 if identity.can_read_all_group_messages else 0),
                    credential_reference_id=reference_id,
                    credential_revision=metadata.revision,
                    verified_at=verified_at,
                    verification_status="verified",
                )
            )
        self.credentials.mark_verified(reference_id, metadata.revision, verified_at)
        return identity

    def get(self, slot: TelegramBotSlot) -> TelegramBotIdentity | None:
        with self.db.session() as session:
            record = session.get(TelegramBotIdentityRecord, slot)
            return self._identity(record) if record is not None else None

    def list(self) -> builtins.list[TelegramBotIdentity]:
        with self.db.session() as session:
            records = list(
                session.scalars(
                    select(TelegramBotIdentityRecord).order_by(TelegramBotIdentityRecord.slot)
                )
            )
            return [self._identity(record) for record in records]

    def require_all_verified(self) -> builtins.list[TelegramBotIdentity]:
        identities = {item.slot: item for item in self.list()}
        missing = [slot for slot in PUBLIC_CREDENTIAL_REFERENCES if slot not in identities]
        if missing:
            raise OperationExecutionError(
                "TELEGRAM_IDENTITIES_INCOMPLETE",
                "All three Telegram bot identities must be verified before binding.",
                recovery_actions=["verify_all_bot_identities"],
            )
        for slot, identity in identities.items():
            metadata = self.credentials.get(identity.credential_reference_id)
            if (
                metadata.status != CredentialStatus.AVAILABLE
                or metadata.revision != identity.credential_revision
            ):
                raise OperationExecutionError(
                    "TELEGRAM_IDENTITY_STALE",
                    f"Telegram identity metadata for slot {slot} is stale after credential rotation.",
                    recovery_actions=["verify_bot_identity"],
                )
        return [identities[slot] for slot in ("hermes", "claude", "codex")]

    def webhook_info(
        self,
        slot: TelegramBotSlot,
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> TelegramWebhookInfo:
        identity = self.get(slot)
        if identity is None:
            raise OperationExecutionError(
                "TELEGRAM_IDENTITY_NOT_VERIFIED",
                "Telegram bot identity is not verified.",
                recovery_actions=["verify_bot_identity"],
            )
        try:
            with self.credentials.resolve_for_operation(identity.credential_reference_id) as token:
                return asyncio.run(self.client.get_webhook_info(token, cancel_event=cancel_event))
        except TelegramApiError as exc:
            raise OperationExecutionError(
                exc.code,
                exc.message,
                retryable=exc.retryable,
                recovery_actions=["retry_webhook_check"],
            ) from None

    def assert_no_webhook(
        self,
        slots: builtins.list[TelegramBotSlot],
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        for slot in slots:
            info = self.webhook_info(slot, cancel_event=cancel_event)
            if info.url_present:
                raise OperationExecutionError(
                    "TELEGRAM_WEBHOOK_CONFLICT",
                    f"Telegram bot slot {slot} has an active webhook; it was not deleted.",
                    recovery_actions=["confirm_and_delete_webhook_outside_runtime_start"],
                )

    def delete_webhook(
        self,
        slot: TelegramBotSlot,
        *,
        explicit_confirmation: bool,
        drop_pending_updates: bool = False,
    ) -> bool:
        identity = self.get(slot)
        if identity is None:
            raise OperationExecutionError(
                "TELEGRAM_IDENTITY_NOT_VERIFIED",
                "Telegram bot identity is not verified.",
                recovery_actions=["verify_bot_identity"],
            )
        try:
            with self.credentials.resolve_for_operation(identity.credential_reference_id) as token:
                return asyncio.run(
                    self.client.delete_webhook(
                        token,
                        explicit_confirmation=explicit_confirmation,
                        drop_pending_updates=drop_pending_updates,
                    )
                )
        except TelegramApiError as exc:
            raise OperationExecutionError(
                exc.code,
                exc.message,
                retryable=exc.retryable,
                recovery_actions=["retry_explicit_webhook_delete"],
            ) from None

    @staticmethod
    def _identity(record: TelegramBotIdentityRecord) -> TelegramBotIdentity:
        return TelegramBotIdentity(
            slot=cast(TelegramBotSlot, record.slot),
            bot_id=record.bot_id,
            username=record.username,
            first_name=record.first_name,
            can_join_groups=bool(record.can_join_groups),
            can_read_all_group_messages=bool(record.can_read_all_group_messages),
            credential_reference_id=record.credential_reference_id,
            credential_revision=record.credential_revision,
            verified_at=record.verified_at,
            verification_status=cast(
                Literal["verified", "invalid", "unknown"],
                record.verification_status,
            ),
        )

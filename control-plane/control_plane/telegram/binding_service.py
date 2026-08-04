from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from urllib.parse import quote

from sqlalchemy import select

from ..credentials.models import INTERNAL_BINDING_HMAC_REFERENCE
from ..credentials.service import CredentialService
from ..operations import ExecutionContext, OperationExecutionError
from ..persistence.models import (
    TelegramBindingAuditRecord,
    TelegramBindingSessionRecord,
    TelegramBindingSlotRecord,
    TelegramGroupBindingRecord,
)
from ..persistence.session import Database
from .api_client import TelegramApiError, TelegramBotApiClient
from .bot_identity import TelegramBotIdentityService
from .models import (
    BindingSession,
    BindingSessionCreated,
    BindingSlotProgress,
    BindingState,
    TelegramBotSlot,
    UpdateOwner,
)
from .update_lease import TelegramUpdateLeaseService

SLOTS: tuple[TelegramBotSlot, ...] = ("hermes", "claude", "codex")


def utcnow() -> datetime:
    return datetime.now(UTC)


class TelegramBindingService:
    def __init__(
        self,
        database: Database,
        credentials: CredentialService,
        identities: TelegramBotIdentityService,
        leases: TelegramUpdateLeaseService,
        client: TelegramBotApiClient | None = None,
    ) -> None:
        self.db = database
        self.credentials = credentials
        self.identities = identities
        self.leases = leases
        self.client = client or identities.client

    def create(self, *, expires_in_seconds: int) -> BindingSessionCreated:
        identities = self.identities.require_all_verified()
        for slot in SLOTS:
            lease = self.leases.get(slot)
            if lease.owner != UpdateOwner.NONE:
                raise OperationExecutionError(
                    "TELEGRAM_UPDATE_OWNER_NOT_RELEASED",
                    f"Telegram bot slot {slot} is already owned by another update consumer.",
                    recovery_actions=["stop_corresponding_runtime", "release_update_owner"],
                )
        self.credentials.ensure_internal_runtime_credentials()
        code = secrets.token_urlsafe(9).replace("-", "A").replace("_", "B")
        session_id = f"binding-{secrets.token_hex(8)}"
        now = utcnow()
        expires_at = now + timedelta(seconds=expires_in_seconds)
        with self.credentials.resolve_for_operation(INTERNAL_BINDING_HMAC_REFERENCE) as key:
            code_digest = self._code_digest(key, session_id, code)
        with self.db.session() as session:
            session.add(
                TelegramBindingSessionRecord(
                    session_id=session_id,
                    code_digest=code_digest,
                    state=BindingState.WAITING_PRIVATE.value,
                    expires_at=expires_at,
                    operator_user_id=None,
                    group_chat_id=None,
                    group_title=None,
                    group_type=None,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                    completed_at=None,
                    canceled_at=None,
                    failure_code=None,
                )
            )
            for identity in identities:
                session.add(
                    TelegramBindingSlotRecord(
                        session_id=session_id,
                        slot=identity.slot,
                        bot_id=identity.bot_id,
                        username=identity.username,
                        credential_revision=identity.credential_revision,
                        private_status="pending",
                        group_status="pending",
                        private_user_id=None,
                        group_chat_id=None,
                        group_title=None,
                        group_type=None,
                        private_update_id=None,
                        group_update_id=None,
                        last_update_id=None,
                        updated_at=now,
                    )
                )
            self._audit(
                session, session_id, None, "binding.created", {"expires_at": expires_at.isoformat()}
            )
        model = self.get(session_id)
        private_links = {
            item.slot: f"https://t.me/{quote(item.username, safe='')}" for item in identities
        }
        private_commands = {item.slot: f"/bind {code}" for item in identities}
        group_commands = {item.slot: f"/bind@{item.username} {code}" for item in identities}
        return BindingSessionCreated(
            **model.model_dump(),
            bind_code=code,
            private_deep_links=private_links,
            private_commands=private_commands,
            group_commands=group_commands,
        )

    def get(self, session_id: str) -> BindingSession:
        with self.db.session() as session:
            record = session.get(TelegramBindingSessionRecord, session_id)
            if record is None:
                raise OperationExecutionError(
                    "TELEGRAM_BINDING_NOT_FOUND",
                    "Telegram binding session was not found.",
                )
            self._expire_if_needed(session, record)
            slots = list(
                session.scalars(
                    select(TelegramBindingSlotRecord)
                    .where(TelegramBindingSlotRecord.session_id == session_id)
                    .order_by(TelegramBindingSlotRecord.slot)
                )
            )
            return self._model(record, slots)

    def cancel(self, session_id: str, reason: str) -> BindingSession:
        now = utcnow()
        with self.db.session() as session:
            record = session.get(TelegramBindingSessionRecord, session_id)
            if record is None:
                raise OperationExecutionError(
                    "TELEGRAM_BINDING_NOT_FOUND", "Telegram binding session was not found."
                )
            if record.state not in {
                BindingState.COMPLETED.value,
                BindingState.CANCELED.value,
                BindingState.EXPIRED.value,
            }:
                record.state = BindingState.CANCELED.value
                record.canceled_at = now
                record.updated_at = now
                record.revision += 1
                self._audit(session, session_id, None, "binding.canceled", {"reason": reason})
        for slot in SLOTS:
            lease = self.leases.get(slot)
            if lease.owner == UpdateOwner.CONTROL_PLANE_BINDING:
                self.leases.release(slot, lease.operation_id, reason)
        return self.get(session_id)

    def poll(self, context: ExecutionContext) -> dict[str, Any]:
        session_id = str(context.payload["session_id"])
        slot = str(context.payload["slot"])
        timeout_seconds = int(context.payload.get("timeout_seconds", 10))
        if slot not in SLOTS:
            raise OperationExecutionError("TELEGRAM_SLOT_INVALID", "Telegram bot slot is invalid.")
        typed_slot = cast(TelegramBotSlot, slot)
        binding = self.get(session_id)
        if binding.state in {
            BindingState.COMPLETED,
            BindingState.CANCELED,
            BindingState.EXPIRED,
            BindingState.CONFLICT,
            BindingState.FAILED,
        }:
            return binding.model_dump(mode="json")
        identity = self.identities.get(typed_slot)
        if identity is None:
            raise OperationExecutionError(
                "TELEGRAM_IDENTITY_NOT_VERIFIED",
                "Telegram bot identity is not verified.",
                recovery_actions=["verify_bot_identity"],
            )
        metadata = self.credentials.get(identity.credential_reference_id)
        lease = self.leases.acquire(
            typed_slot,
            UpdateOwner.CONTROL_PLANE_BINDING,
            context.operation_id,
            metadata.revision,
            ttl_seconds=max(60, timeout_seconds + 30),
        )
        try:
            context.safe_checkpoint()
            info = self.identities.webhook_info(typed_slot)
            if info.url_present:
                self._set_state(session_id, BindingState.CONFLICT, "TELEGRAM_WEBHOOK_CONFLICT")
                raise OperationExecutionError(
                    "TELEGRAM_WEBHOOK_CONFLICT",
                    "Telegram bot has an active webhook; Control Plane did not delete it.",
                    recovery_actions=["explicitly_resolve_webhook_owner"],
                )
            with self.credentials.resolve_for_operation(identity.credential_reference_id) as token:
                try:
                    updates = asyncio.run(
                        self.client.get_updates(
                            token,
                            offset=lease.offset,
                            timeout_seconds=timeout_seconds,
                        )
                    )
                except TelegramApiError as exc:
                    raise OperationExecutionError(
                        exc.code,
                        exc.message,
                        retryable=exc.retryable,
                        recovery_actions=["retry_binding_poll"],
                    ) from None
            for update in updates:
                context.safe_checkpoint()
                self._process_update(session_id, typed_slot, update.update_id, update.payload)
                self.leases.heartbeat(
                    typed_slot,
                    context.operation_id,
                    next_offset=update.update_id + 1,
                    ttl_seconds=max(60, timeout_seconds + 30),
                )
            return self.get(session_id).model_dump(mode="json")
        finally:
            self.leases.release(typed_slot, context.operation_id, "binding_poll_finished")

    def recovery_probe(self, _operation_id: str, payload: dict[str, Any]):
        from ..operations import RecoveryDecision

        try:
            state = self.get(str(payload.get("session_id", "")))
        except OperationExecutionError:
            return RecoveryDecision.fail(code="TELEGRAM_BINDING_RECOVERY_NOT_FOUND")
        if state.state == BindingState.COMPLETED:
            return RecoveryDecision.complete(state.model_dump(mode="json"))
        if state.state in {
            BindingState.WAITING_PRIVATE,
            BindingState.WAITING_GROUP,
            BindingState.PARTIALLY_BOUND,
        }:
            return RecoveryDecision.requeue()
        return RecoveryDecision.fail(code="TELEGRAM_BINDING_RECOVERY_REQUIRES_REVIEW")

    def _process_update(
        self, session_id: str, slot: TelegramBotSlot, update_id: int, payload: dict[str, Any]
    ) -> None:
        message = payload.get("message")
        if not isinstance(message, dict):
            return
        text = message.get("text")
        chat = message.get("chat")
        sender = message.get("from")
        if not isinstance(text, str) or not isinstance(chat, dict) or not isinstance(sender, dict):
            return
        try:
            sender_id = int(sender["id"])
            chat_id = int(chat["id"])
            chat_type = str(chat["type"])
            message_date = int(message.get("date", 0))
        except (KeyError, TypeError, ValueError):
            return
        with self.db.session() as session:
            binding = session.get(TelegramBindingSessionRecord, session_id)
            progress = session.get(TelegramBindingSlotRecord, (session_id, slot))
            if binding is None or progress is None:
                return
            self._expire_if_needed(session, binding)
            if binding.state in {
                BindingState.CANCELED.value,
                BindingState.EXPIRED.value,
                BindingState.COMPLETED.value,
                BindingState.FAILED.value,
            }:
                return
            progress.last_update_id = max(progress.last_update_id or 0, update_id)
            progress.updated_at = utcnow()
            created_epoch = int(
                binding.created_at.replace(tzinfo=binding.created_at.tzinfo or UTC).timestamp()
            )
            if message_date and message_date + 5 < created_epoch:
                self._audit(
                    session,
                    session_id,
                    slot,
                    "binding.old_update_ignored",
                    {"update_id": update_id},
                )
                return
            expected_code = self._extract_code(text, chat_type, progress.username)
            if expected_code is None:
                return
            with self.credentials.resolve_for_operation(INTERNAL_BINDING_HMAC_REFERENCE) as key:
                digest = self._code_digest(key, session_id, expected_code)
            if not hmac.compare_digest(digest, binding.code_digest):
                self._audit(
                    session, session_id, slot, "binding.code_rejected", {"update_id": update_id}
                )
                return
            if chat_type == "private":
                if progress.private_status == "bound":
                    self._audit(
                        session,
                        session_id,
                        slot,
                        "binding.private_replay_ignored",
                        {"update_id": update_id},
                    )
                    return
                if binding.operator_user_id is None:
                    binding.operator_user_id = sender_id
                elif binding.operator_user_id != sender_id:
                    progress.private_status = "rejected"
                    self._audit(
                        session,
                        session_id,
                        slot,
                        "binding.operator_hijack_rejected",
                        {"update_id": update_id},
                    )
                    return
                progress.private_status = "bound"
                progress.private_user_id = sender_id
                progress.private_update_id = update_id
                self._audit(
                    session, session_id, slot, "binding.private_bound", {"update_id": update_id}
                )
            elif chat_type in {"group", "supergroup"}:
                if progress.group_status == "bound":
                    self._audit(
                        session,
                        session_id,
                        slot,
                        "binding.group_replay_ignored",
                        {"update_id": update_id},
                    )
                    return
                if binding.operator_user_id is None or binding.operator_user_id != sender_id:
                    progress.group_status = "rejected"
                    self._audit(
                        session,
                        session_id,
                        slot,
                        "binding.group_operator_rejected",
                        {"update_id": update_id},
                    )
                    return
                progress.group_status = "bound"
                progress.group_chat_id = chat_id
                progress.group_title = str(chat.get("title", ""))[:512] or None
                progress.group_type = chat_type
                progress.group_update_id = update_id
                self._audit(
                    session, session_id, slot, "binding.group_bound", {"update_id": update_id}
                )
            elif chat_type == "channel":
                self._audit(
                    session, session_id, slot, "binding.channel_rejected", {"update_id": update_id}
                )
                return
            else:
                return
            binding.updated_at = utcnow()
            binding.revision += 1
            self._recalculate(session, binding)

    @staticmethod
    def _extract_code(text: str, chat_type: str, username: str) -> str | None:
        parts = text.strip().split()
        if len(parts) != 2:
            return None
        command, code = parts
        command_lower = command.casefold()
        if chat_type == "private":
            if command_lower == "/bind":
                return code
            if command_lower == f"/bind@{username}".casefold():
                return code
            if command_lower == "/start" and code.startswith("bind_"):
                return code.removeprefix("bind_")
            return None
        if chat_type in {"group", "supergroup"} and command_lower == f"/bind@{username}".casefold():
            return code
        return None

    def _recalculate(self, session, binding: TelegramBindingSessionRecord) -> None:
        slots = list(
            session.scalars(
                select(TelegramBindingSlotRecord).where(
                    TelegramBindingSlotRecord.session_id == binding.session_id
                )
            )
        )
        private_count = sum(item.private_status == "bound" for item in slots)
        group_count = sum(item.group_status == "bound" for item in slots)
        if private_count < 3:
            binding.state = (
                BindingState.PARTIALLY_BOUND.value
                if private_count
                else BindingState.WAITING_PRIVATE.value
            )
            return
        if group_count < 3:
            binding.state = (
                BindingState.PARTIALLY_BOUND.value
                if group_count
                else BindingState.WAITING_GROUP.value
            )
            return
        group_ids = {item.group_chat_id for item in slots}
        user_ids = {item.private_user_id for item in slots}
        group_types = {item.group_type for item in slots}
        if (
            len(group_ids) != 1
            or len(user_ids) != 1
            or not group_types.issubset({"group", "supergroup"})
        ):
            binding.state = BindingState.CONFLICT.value
            binding.failure_code = "TELEGRAM_GROUP_CONSISTENCY_CONFLICT"
            self._audit(session, binding.session_id, None, "binding.group_consistency_conflict", {})
            return
        binding.group_chat_id = next(iter(group_ids))
        binding.group_title = next((item.group_title for item in slots if item.group_title), None)
        binding.group_type = "supergroup" if "supergroup" in group_types else "group"
        binding.state = BindingState.COMPLETED.value
        binding.completed_at = utcnow()
        for item in slots:
            session.merge(
                TelegramGroupBindingRecord(
                    session_id=binding.session_id,
                    slot=item.slot,
                    operator_user_id=binding.operator_user_id,
                    group_chat_id=binding.group_chat_id,
                    group_title=binding.group_title,
                    group_type=binding.group_type,
                    binding_revision=binding.revision,
                    created_at=utcnow(),
                )
            )
        self._audit(session, binding.session_id, None, "binding.completed", {"bound": "3/3"})

    def _set_state(self, session_id: str, state: BindingState, failure_code: str) -> None:
        with self.db.session() as session:
            record = session.get(TelegramBindingSessionRecord, session_id)
            if record is not None:
                record.state = state.value
                record.failure_code = failure_code
                record.updated_at = utcnow()
                record.revision += 1

    @staticmethod
    def _expire_if_needed(session, record: TelegramBindingSessionRecord) -> None:
        expires = record.expires_at.replace(tzinfo=record.expires_at.tzinfo or UTC)
        if expires <= utcnow() and record.state not in {
            BindingState.COMPLETED.value,
            BindingState.CANCELED.value,
            BindingState.EXPIRED.value,
        }:
            record.state = BindingState.EXPIRED.value
            record.updated_at = utcnow()
            record.revision += 1

    @staticmethod
    def _code_digest(key: str, session_id: str, code: str) -> str:
        payload = f"{session_id}\0{code}".encode()
        return "hmac-sha256:" + hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()

    @staticmethod
    def _audit(
        session, session_id: str, slot: str | None, event_type: str, data: dict[str, Any]
    ) -> None:
        session.add(
            TelegramBindingAuditRecord(
                session_id=session_id,
                slot=slot,
                event_type=event_type,
                data_json=json.dumps(data, sort_keys=True),
                created_at=utcnow(),
            )
        )

    @staticmethod
    def _model(
        record: TelegramBindingSessionRecord, slots: list[TelegramBindingSlotRecord]
    ) -> BindingSession:
        progress = [
            BindingSlotProgress(
                slot=cast(TelegramBotSlot, item.slot),
                bot_id=item.bot_id,
                username=item.username,
                private_status=cast(Literal["pending", "bound", "rejected"], item.private_status),
                group_status=cast(Literal["pending", "bound", "rejected"], item.group_status),
                private_user_id=item.private_user_id,
                group_chat_id=item.group_chat_id,
                group_title=item.group_title,
                group_type=cast(Literal["group", "supergroup"] | None, item.group_type),
                last_update_id=item.last_update_id,
            )
            for item in slots
        ]
        return BindingSession(
            session_id=record.session_id,
            state=BindingState(record.state),
            expires_at=record.expires_at,
            operator_user_id=record.operator_user_id,
            group_chat_id=record.group_chat_id,
            group_title=record.group_title,
            group_type=cast(Literal["group", "supergroup"] | None, record.group_type),
            slots=progress,
            bound_private_count=sum(item.private_status == "bound" for item in slots),
            bound_group_count=sum(item.group_status == "bound" for item in slots),
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
            completed_at=record.completed_at,
        )

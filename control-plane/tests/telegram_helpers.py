from __future__ import annotations

import threading
import time
from typing import Any

from control_plane.credentials.models import PUBLIC_CREDENTIAL_REFERENCES
from control_plane.credentials.service import CredentialService
from control_plane.credentials.windows_backend import InMemorySecretBackend
from control_plane.operations import ExecutionContext
from control_plane.telegram.binding_service import SLOTS, TelegramBindingService
from control_plane.telegram.bot_identity import TelegramBotIdentityService
from control_plane.telegram.models import TelegramUpdate, TelegramWebhookInfo
from control_plane.telegram.update_lease import TelegramUpdateLeaseService

TOKENS = {
    "hermes": "100001:synthetic-hermes-token",
    "claude": "100002:synthetic-claude-token",
    "codex": "100003:synthetic-codex-token",
}


class FakeTelegramClient:
    def __init__(self) -> None:
        self.identities = {
            TOKENS[slot]: {
                "id": 9000 + index,
                "is_bot": True,
                "username": f"aiad_{slot}_bot",
                "first_name": slot.title(),
                "can_join_groups": True,
                "can_read_all_group_messages": False,
            }
            for index, slot in enumerate(SLOTS, start=1)
        }
        self.webhooks: dict[str, bool] = {token: False for token in TOKENS.values()}
        self.updates: dict[str, list[TelegramUpdate]] = {token: [] for token in TOKENS.values()}

    async def get_me(self, token: str, *, cancel_event=None) -> dict[str, Any]:
        del cancel_event
        return dict(self.identities[token])

    async def get_webhook_info(self, token: str, *, cancel_event=None) -> TelegramWebhookInfo:
        del cancel_event
        return TelegramWebhookInfo(url_present=self.webhooks[token])

    async def get_updates(
        self,
        token: str,
        *,
        offset: int,
        timeout_seconds: int,
        cancel_event=None,
    ) -> list[TelegramUpdate]:
        del timeout_seconds, cancel_event
        return [item for item in self.updates[token] if item.update_id >= offset]

    async def delete_webhook(
        self,
        token: str,
        *,
        explicit_confirmation: bool,
        drop_pending_updates: bool = False,
        cancel_event=None,
    ) -> bool:
        del cancel_event
        if not explicit_confirmation:
            raise AssertionError("explicit confirmation required")
        self.webhooks[token] = False
        if drop_pending_updates:
            self.updates[token].clear()
        return True

    def add_update(self, slot: str, update_id: int, payload: dict[str, Any]) -> None:
        self.updates[TOKENS[slot]].append(TelegramUpdate(update_id=update_id, payload=payload))


def message_update(
    *,
    update_id: int,
    text: str,
    sender_id: int,
    chat_id: int,
    chat_type: str,
    title: str | None = None,
    message_date: int | None = None,
) -> dict[str, Any]:
    chat: dict[str, Any] = {"id": chat_id, "type": chat_type}
    if title:
        chat["title"] = title
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": message_date or int(time.time()),
            "text": text,
            "from": {"id": sender_id, "is_bot": False},
            "chat": chat,
        },
    }


def build_telegram_services(database):
    backend = InMemorySecretBackend()
    credentials = CredentialService(database, backend)
    client = FakeTelegramClient()
    identities = TelegramBotIdentityService(database, credentials, client)  # type: ignore[arg-type]
    leases = TelegramUpdateLeaseService(database)
    bindings = TelegramBindingService(
        database,
        credentials,
        identities,
        leases,
        client,  # type: ignore[arg-type]
    )
    for slot in SLOTS:
        credentials.put(
            PUBLIC_CREDENTIAL_REFERENCES[slot][0],
            TOKENS[slot],
            operation_id=f"credential-{slot}",
        )
        identities.verify(slot)
    return backend, credentials, client, identities, leases, bindings


def complete_binding(database, client: FakeTelegramClient, bindings: TelegramBindingService):
    created = bindings.create(expires_in_seconds=900)
    for index, slot in enumerate(SLOTS, start=1):
        client.add_update(
            slot,
            index,
            message_update(
                update_id=index,
                text=created.private_commands[slot],
                sender_id=777001,
                chat_id=777001,
                chat_type="private",
            ),
        )
        bindings.poll(
            ExecutionContext(
                operation_id=f"private-{slot}",
                component_id=f"telegram:{slot}",
                kind="telegram_binding_poll",
                payload={"session_id": created.session_id, "slot": slot, "timeout_seconds": 0},
                database=database,
                shutdown_event=threading.Event(),
            )
        )
    for index, slot in enumerate(SLOTS, start=11):
        client.add_update(
            slot,
            index,
            message_update(
                update_id=index,
                text=created.group_commands[slot],
                sender_id=777001,
                chat_id=-100777001,
                chat_type="supergroup",
                title="AI 编程组",
            ),
        )
        bindings.poll(
            ExecutionContext(
                operation_id=f"group-{slot}",
                component_id=f"telegram:{slot}",
                kind="telegram_binding_poll",
                payload={"session_id": created.session_id, "slot": slot, "timeout_seconds": 0},
                database=database,
                shutdown_event=threading.Event(),
            )
        )
    return created, bindings.get(created.session_id)

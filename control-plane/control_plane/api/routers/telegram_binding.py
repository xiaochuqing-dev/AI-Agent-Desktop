from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Header, Request, Response

from ...application.operation_store import OperationStore
from ...domain.models import ResourceRef
from ...observability.models import ProxyPolicyState
from ...operations import OperationExecutionError
from ...security.redaction import redact_value
from ...telegram.models import (
    BindingCancelRequest,
    BindingCreateRequest,
    BindingPollRequest,
    BindingResumeRequest,
    BindingSession,
    BindingSessionCreated,
    TelegramBotIdentity,
    TelegramBotSlot,
    TelegramGroupVerification,
    TelegramUpdateLease,
    WebhookDeleteRequest,
)


def build_telegram_router(
    get_state: Callable[[], Any], bearer_auth: Callable[..., str]
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/telegram", tags=["Telegram"])

    def operation(
        *,
        kind: str,
        component_id: str,
        target_kind: str,
        target_id: str,
        resource: str,
        idempotency_key: str,
        body: bytes,
        payload: dict[str, Any],
    ):
        state = get_state()
        with state.db.session() as session:
            created, reused = OperationStore(session).create(
                kind=kind,
                target_ref=ResourceRef(kind=target_kind, id=target_id),
                idempotency_key=idempotency_key,
                method="POST",
                resource=resource,
                body=body,
            )
        if not reused:
            state.executor.submit(
                operation_id=created.operation_id,
                component_id=component_id,
                kind=kind,
                payload=payload,
            )
        return created

    @router.get("/bots", response_model=list[TelegramBotIdentity])
    def list_bots(_token: str = Depends(bearer_auth)):
        return redact_value(
            [item.model_dump(mode="json") for item in get_state().telegram_identities.list()]
        )

    @router.get("/bots/{slot}", response_model=TelegramBotIdentity | None)
    def get_bot(slot: TelegramBotSlot, _token: str = Depends(bearer_auth)):
        identity = get_state().telegram_identities.get(slot)
        return redact_value(identity.model_dump(mode="json") if identity else None)

    @router.post("/bots/{slot}:verify", status_code=202)
    async def verify_bot(
        slot: TelegramBotSlot,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(bearer_auth),
    ):
        created = operation(
            kind="telegram_bot_verify",
            component_id=f"telegram:{slot}",
            target_kind="telegram_bot",
            target_id=slot,
            resource=f"/api/v1/telegram/bots/{slot}:verify",
            idempotency_key=idempotency_key,
            body=await request.body(),
            payload={"slot": slot},
        )
        response.headers["Location"] = f"/api/v1/operations/{created.operation_id}"
        return redact_value(created.model_dump(mode="json"))

    @router.get("/bots/{slot}/webhook")
    def webhook_info(slot: TelegramBotSlot, _token: str = Depends(bearer_auth)):
        return redact_value(
            get_state().telegram_identities.webhook_info(slot).model_dump(mode="json")
        )

    @router.post("/bots/{slot}/webhook:delete", status_code=202)
    async def delete_webhook(
        slot: TelegramBotSlot,
        payload: WebhookDeleteRequest,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(bearer_auth),
    ):
        created = operation(
            kind="telegram_webhook_delete",
            component_id=f"telegram:{slot}",
            target_kind="telegram_bot",
            target_id=slot,
            resource=f"/api/v1/telegram/bots/{slot}/webhook:delete",
            idempotency_key=idempotency_key,
            body=await request.body(),
            payload={
                "slot": slot,
                "explicit_confirmation": payload.explicit_confirmation,
                "drop_pending_updates": payload.drop_pending_updates,
            },
        )
        response.headers["Location"] = f"/api/v1/operations/{created.operation_id}"
        return redact_value(created.model_dump(mode="json"))

    @router.get("/update-leases", response_model=list[TelegramUpdateLease])
    def update_leases(_token: str = Depends(bearer_auth)):
        state = get_state()
        return redact_value(
            [
                state.telegram_leases.get(slot).model_dump(mode="json")
                for slot in ("hermes", "claude", "codex")
            ]
        )

    @router.get("/network-policy", response_model=ProxyPolicyState)
    def network_policy(_token: str = Depends(bearer_auth)):
        client = get_state().telegram_client
        policy = getattr(client, "proxy_policy", None)
        if policy is None:
            return ProxyPolicyState(mode="direct", source="none", status="ready")
        resolver = getattr(client, "proxy_secret_resolver", None)
        return redact_value(policy.state(secret_resolver=resolver).model_dump(mode="json"))

    @router.post("/bindings", response_model=BindingSessionCreated, status_code=201)
    def create_binding(
        payload: BindingCreateRequest,
        _token: str = Depends(bearer_auth),
    ):
        lifecycle = get_state().lifecycle.status()
        if lifecycle.observed_state in {"starting", "running_partial"}:
            raise OperationExecutionError(
                "TELEGRAM_BINDING_REQUIRES_STOPPED_RUNTIMES",
                "Product-managed cc-connect must be stopped before Control Plane acquires getUpdates.",
                recovery_actions=["stop_product_managed_cc_connect"],
            )
        return redact_value(
            get_state()
            .telegram_binding.create(expires_in_seconds=payload.expires_in_seconds)
            .model_dump(mode="json")
        )

    @router.get("/bindings/{session_id}", response_model=BindingSession)
    def get_binding(session_id: str, _token: str = Depends(bearer_auth)):
        return redact_value(get_state().telegram_binding.get(session_id).model_dump(mode="json"))

    @router.post(
        "/bindings/{session_id}:resume",
        response_model=BindingSessionCreated,
        status_code=200,
    )
    def resume_binding(
        session_id: str,
        payload: BindingResumeRequest,
        _token: str = Depends(bearer_auth),
    ):
        lifecycle = get_state().lifecycle.status()
        if lifecycle.observed_state in {"starting", "running_partial"}:
            raise OperationExecutionError(
                "TELEGRAM_BINDING_REQUIRES_STOPPED_RUNTIMES",
                "Product-managed cc-connect must be stopped before Control Plane acquires getUpdates.",
                recovery_actions=["stop_product_managed_cc_connect"],
            )
        return redact_value(
            get_state()
            .telegram_binding.resume(
                session_id,
                expires_in_seconds=payload.expires_in_seconds,
            )
            .model_dump(mode="json")
        )

    @router.get(
        "/bindings/{session_id}/slots/{slot}/group-verification",
        response_model=TelegramGroupVerification,
    )
    def group_verification(
        session_id: str,
        slot: TelegramBotSlot,
        _token: str = Depends(bearer_auth),
    ):
        state = get_state()
        binding = state.telegram_binding.get(session_id)
        progress = next((item for item in binding.slots if item.slot == slot), None)
        identity = state.telegram_identities.get(slot)
        if progress is None or progress.group_chat_id is None or identity is None:
            raise OperationExecutionError(
                "TELEGRAM_GROUP_NOT_BOUND",
                "Telegram group has not been detected for this bot.",
                recovery_actions=["complete_group_binding"],
            )
        chat = state.telegram_identities.get_chat(slot, progress.group_chat_id)
        membership = state.telegram_identities.get_chat_member(
            slot, progress.group_chat_id, identity.bot_id
        )
        raw_status = str(membership.get("status", "unknown"))
        allowed_statuses = {
            "creator",
            "administrator",
            "member",
            "restricted",
            "left",
            "kicked",
            "unknown",
        }
        status = raw_status if raw_status in allowed_statuses else "unknown"
        active = status in {"creator", "administrator", "member", "restricted"}
        result = TelegramGroupVerification(
            slot=slot,
            group_title=str(chat.get("title", ""))[:512] or progress.group_title,
            group_type=progress.group_type or "group",
            bot_status=cast(
                Literal[
                    "creator",
                    "administrator",
                    "member",
                    "restricted",
                    "left",
                    "kicked",
                    "unknown",
                ],
                status,
            ),
            can_send_messages=(
                bool(membership.get("can_send_messages"))
                if "can_send_messages" in membership
                else (True if active else False)
            ),
            privacy_mode_warning=not identity.can_read_all_group_messages,
            user_message=(
                "Bot 已加入群；如需响应普通群消息，请在 BotFather 检查 Privacy Mode。"
                if active and not identity.can_read_all_group_messages
                else ("Bot 已加入群。" if active else "Bot 当前不在群内。")
            ),
        )
        return redact_value(result.model_dump(mode="json"))

    @router.post("/bindings/{session_id}:cancel", response_model=BindingSession)
    def cancel_binding(
        session_id: str,
        payload: BindingCancelRequest,
        _token: str = Depends(bearer_auth),
    ):
        return redact_value(
            get_state().telegram_binding.cancel(session_id, payload.reason).model_dump(mode="json")
        )

    @router.post("/bindings/{session_id}/slots/{slot}:poll", status_code=202)
    async def poll_binding(
        session_id: str,
        slot: TelegramBotSlot,
        payload: BindingPollRequest,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(bearer_auth),
    ):
        created = operation(
            kind="telegram_binding_poll",
            component_id=f"telegram:{slot}",
            target_kind="telegram_binding",
            target_id=session_id,
            resource=f"/api/v1/telegram/bindings/{session_id}/slots/{slot}:poll",
            idempotency_key=idempotency_key,
            body=await request.body(),
            payload={
                "session_id": session_id,
                "slot": slot,
                "timeout_seconds": payload.timeout_seconds,
            },
        )
        response.headers["Location"] = f"/api/v1/operations/{created.operation_id}"
        return redact_value(created.model_dump(mode="json"))

    return router

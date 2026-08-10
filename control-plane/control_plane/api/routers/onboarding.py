from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends
from sqlalchemy import select

from ...credentials.models import PUBLIC_CREDENTIAL_REFERENCES
from ...onboarding.models import (
    DashboardAgentSnapshot,
    DashboardSnapshot,
    OnboardingAgentSnapshot,
    OnboardingBindingSnapshot,
    OnboardingChecklistItem,
    OnboardingSnapshot,
    Slot,
    TelegramClientAvailability,
)
from ...persistence.models import TelegramBindingSessionRecord
from ...security.redaction import redact_value
from ...telegram.client_discovery import TelegramClientDiscovery

SLOTS: tuple[Slot, ...] = ("hermes", "claude", "codex")
DISPLAY_NAMES = {"hermes": "Hermes", "claude": "Claude Code", "codex": "Codex"}


def _now() -> datetime:
    return datetime.now(UTC)


def _binding_snapshot(state: Any) -> OnboardingBindingSnapshot:
    with state.db.session() as session:
        record = session.scalar(
            select(TelegramBindingSessionRecord)
            .order_by(TelegramBindingSessionRecord.created_at.desc())
            .limit(1)
        )
    if record is None:
        return OnboardingBindingSnapshot()
    binding = state.telegram_binding.get(record.session_id)
    return OnboardingBindingSnapshot(
        session_id=binding.session_id,
        state=binding.state.value,
        expires_at=binding.expires_at,
        bound_private_count=binding.bound_private_count,
        bound_group_count=binding.bound_group_count,
        group_title=binding.group_title,
        group_type=binding.group_type,
        revision=binding.revision,
    )


def _agent_snapshots(
    state: Any, binding: OnboardingBindingSnapshot
) -> list[OnboardingAgentSnapshot]:
    identities = {item.slot: item for item in state.telegram_identities.list()}
    binding_model = state.telegram_binding.get(binding.session_id) if binding.session_id else None
    snapshots: list[OnboardingAgentSnapshot] = []
    for slot in SLOTS:
        identity = identities.get(slot)
        token_ready = False
        try:
            reference = (
                identity.credential_reference_id
                if identity
                else PUBLIC_CREDENTIAL_REFERENCES[slot][0]
            )
            token_ready = state.credentials.get(reference).status.value == "available"
        except Exception:
            token_ready = False
        progress = (
            next((item for item in binding_model.slots if item.slot == slot), None)
            if binding_model
            else None
        )
        snapshots.append(
            OnboardingAgentSnapshot(
                slot=cast(Slot, slot),
                display_name=DISPLAY_NAMES[slot],
                bot_username=identity.username if identity else None,
                bot_id=identity.bot_id if identity else None,
                token_ready=token_ready,
                identity_verified=identity is not None
                and identity.verification_status == "verified",
                installed=None,
                connected=None,
                private_status=progress.private_status if progress else "pending",
                group_status=progress.group_status if progress else "pending",
                user_message=("已准备好" if identity is not None else "请输入这个 Bot 的 Token"),
            )
        )
    return snapshots


def _native_configuration_ready(state: Any) -> bool:
    try:
        return state.native_configuration.state().status == "valid"
    except Exception:
        # A missing locked artifact or an unavailable external runtime is a
        # recoverable onboarding state, never a reason to fail the read-only
        # snapshot endpoint.
        return False


def _snapshot(state: Any) -> OnboardingSnapshot:
    observed = _now()
    binding = _binding_snapshot(state)
    agents = _agent_snapshots(state, binding)
    private_count = binding.bound_private_count
    group_count = binding.bound_group_count
    tokens = sum(item.token_ready for item in agents)
    identities_verified = sum(item.identity_verified for item in agents)
    native_ready = _native_configuration_ready(state)
    if tokens < 3 or identities_verified < 3:
        current_step = 1
    elif private_count < 3:
        current_step = 2
    elif group_count < 3:
        current_step = 3
    elif binding.state == "completed" and native_ready:
        current_step = 4
    elif binding.state == "completed":
        current_step = 4
    else:
        current_step = 3
    complete = binding.state == "completed" and native_ready
    checklist = [
        OnboardingChecklistItem(
            key="telegram",
            label="检查 Telegram 连接",
            status="complete" if tokens == 3 and identities_verified == 3 else "needs_action",
            user_message=(
                "Telegram 已准备好"
                if tokens == 3 and identities_verified == 3
                else "还需要录入并验证 3 个 Bot Token"
            ),
        ),
        OnboardingChecklistItem(
            key="agents",
            label="检查 Hermes、Claude Code 和 Codex",
            status="complete" if identities_verified == 3 else "pending",
            user_message="三个 Bot 身份已确认" if identities_verified == 3 else "等待 Bot 身份确认",
        ),
        OnboardingChecklistItem(
            key="runtime",
            label="准备运行环境",
            status="complete"
            if native_ready
            else ("needs_action" if binding.state == "completed" else "pending"),
            user_message="运行环境已准备" if native_ready else "绑定完成后自动准备",
        ),
        OnboardingChecklistItem(
            key="configuration",
            label="生成连接配置",
            status="complete"
            if native_ready
            else ("needs_action" if binding.state == "completed" else "pending"),
            user_message="连接配置已生成" if native_ready else "绑定完成后自动生成",
        ),
        OnboardingChecklistItem(
            key="chat",
            label="检查聊天是否可用",
            status="complete" if binding.state == "completed" else "pending",
            user_message=(
                "可以开始使用"
                if native_ready
                else (
                    "配置已完成，聊天测试仍需你确认"
                    if binding.state == "completed"
                    else "需要完成 Telegram 绑定"
                )
            ),
        ),
    ]
    overall: Literal["ready", "needs_action", "pending", "degraded"] = (
        "ready" if complete else ("needs_action" if current_step in {1, 2, 3, 4} else "pending")
    )
    return OnboardingSnapshot(
        revision=f"onboarding-{binding.revision}-{observed.timestamp():.0f}",
        observed_at=observed,
        current_step=current_step,
        onboarding_complete=complete,
        agents=agents,
        binding=binding,
        checklist=checklist,
        telegram_client=TelegramClientAvailability(
            tg_handler_available=TelegramClientDiscovery().handler_available(),
            checked_at=observed,
        ),
        overall_status=overall,
    )


def build_onboarding_router(
    get_state: Callable[[], Any], bearer_auth: Callable[..., str]
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Onboarding"])

    @router.get("/onboarding/snapshot", response_model=OnboardingSnapshot)
    def onboarding_snapshot(_token: str = Depends(bearer_auth)):
        return redact_value(_snapshot(get_state()).model_dump(mode="json"))

    @router.get("/dashboard/snapshot", response_model=DashboardSnapshot)
    def dashboard_snapshot(_token: str = Depends(bearer_auth)):
        snapshot = _snapshot(get_state())
        status: Literal["ready", "needs_action"] = (
            "ready" if snapshot.overall_status == "ready" else "needs_action"
        )
        return redact_value(
            DashboardSnapshot(
                revision=snapshot.revision,
                observed_at=snapshot.observed_at,
                overall_status=snapshot.overall_status,
                telegram_status=cast(
                    Literal["ready", "needs_action", "unknown"],
                    status if snapshot.binding.bound_private_count == 3 else "needs_action",
                ),
                agents=[
                    DashboardAgentSnapshot(
                        slot=item.slot,
                        display_name=item.display_name,
                        installed=item.installed,
                        connected=item.connected,
                        status="ready" if item.identity_verified else "needs_action",
                        user_message=item.user_message,
                    )
                    for item in snapshot.agents
                ],
                chat_pills=[
                    "Hermes 私聊",
                    "Hermes 群聊",
                    "Claude 私聊",
                    "Claude 群聊",
                    "Codex 私聊",
                    "Codex 群聊",
                ],
                recent_issues=[
                    item.user_message
                    for item in snapshot.checklist
                    if item.status == "needs_action"
                ],
            ).model_dump(mode="json")
        )

    @router.get("/telegram/client-availability", response_model=TelegramClientAvailability)
    def telegram_client_availability(_token: str = Depends(bearer_auth)):
        return TelegramClientAvailability(
            tg_handler_available=TelegramClientDiscovery().handler_available(),
            checked_at=_now(),
        )

    return router

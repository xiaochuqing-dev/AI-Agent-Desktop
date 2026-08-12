from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from ...agent_detection.models import AgentDetectionResult, AgentDetectionSnapshot
from ...credentials.models import PUBLIC_CREDENTIAL_REFERENCES
from ...observability.models import EvidenceLevel, LinkId, LinkState, LinkStatus
from ...onboarding.models import (
    ChatLinkSnapshot,
    DashboardAgentSnapshot,
    DashboardSnapshot,
    OnboardingAgentSnapshot,
    OnboardingBindingSnapshot,
    OnboardingChecklistItem,
    OnboardingSnapshot,
    RuntimeReadinessSnapshot,
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
    state: Any,
    binding: OnboardingBindingSnapshot,
    detections: dict[str, AgentDetectionResult],
    *,
    runtime_ready: bool,
) -> list[OnboardingAgentSnapshot]:
    identities = {item.slot: item for item in state.telegram_identities.list()}
    binding_model = state.telegram_binding.get(binding.session_id) if binding.session_id else None
    snapshots: list[OnboardingAgentSnapshot] = []
    for slot in SLOTS:
        identity = identities.get(slot)
        detection = detections[slot]
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
                slot=slot,
                display_name=DISPLAY_NAMES[slot],
                bot_username=identity.username if identity else None,
                bot_id=identity.bot_id if identity else None,
                token_ready=token_ready,
                identity_verified=identity is not None
                and identity.verification_status == "verified",
                installed=detection.installed,
                connected=(
                    None if slot == "hermes" else bool(detection.acceptable and runtime_ready)
                ),
                version=detection.version,
                detection_status=detection.status.value,
                probe_status=detection.probe_status.value,
                detection_source=detection.detection_source.value,
                diagnostic_code=detection.diagnostic_code,
                official_install_url=detection.official_install_url,
                acceptable=detection.acceptable,
                private_status=progress.private_status if progress else "pending",
                group_status=progress.group_status if progress else "pending",
                user_message=detection.user_message,
            )
        )
    return snapshots


def _native_configuration_ready(state: Any) -> tuple[bool, int]:
    try:
        native = state.native_configuration.state()
        return native.status == "valid", int(native.revision)
    except Exception:
        return False, 0


def _runtime_readiness(state: Any) -> RuntimeReadinessSnapshot:
    try:
        status = state.lifecycle.status()
        health = status.health
        pid_verified = bool(
            status.pid
            and status.identity
            and status.identity.pid == status.pid
            and status.identity_verification
            and status.identity_verification.status == "verified"
            and health.process_identity_verified
        )
        executable_verified = bool(status.identity and health.artifact_integrity_verified)
        ready = bool(
            status.observed_state == "running_partial"
            and pid_verified
            and executable_verified
            and health.configuration_revision_verified
            and health.port_owned_by_process
            and health.startup_stable_for_window
            and not health.fatal_log_detected
        )
        diagnostic_code = None if ready else "CC_CONNECT_RUNTIME_NOT_READY"
        return RuntimeReadinessSnapshot(
            ready=ready,
            observed_state=status.observed_state,
            pid_verified=pid_verified,
            executable_verified=executable_verified,
            configuration_revision_verified=health.configuration_revision_verified,
            port_owned_by_process=health.port_owned_by_process,
            startup_stable_for_window=health.startup_stable_for_window,
            configuration_revision=status.configuration_revision,
            diagnostic_code=diagnostic_code,
            user_message=(
                "cc-connect 运行环境已通过 PID、可执行文件、配置版本、端口和稳定窗口检查。"
                if ready
                else "cc-connect 运行环境还没有完成真实性检查。"
            ),
        )
    except Exception:
        return RuntimeReadinessSnapshot(
            diagnostic_code="CC_CONNECT_RUNTIME_NOT_READY",
            user_message="暂时无法确认 cc-connect 运行环境。",
        )


def _binding_status(binding: OnboardingBindingSnapshot, link: LinkState) -> str:
    if binding.state in {"conflict", "failed", "canceled"}:
        return "conflict"
    if binding.state == "expired":
        return "expired"
    if link.binding_session_id:
        return "bound"
    return "pending"


def _chat_health_status(link: LinkState) -> str:
    if link.status == LinkStatus.STALE:
        return "stale"
    if link.evidence_level == EvidenceLevel.LIVE_VERIFIED and link.status == LinkStatus.HEALTHY:
        return "live_verified"
    if link.status in {LinkStatus.FAILED, LinkStatus.DEGRADED}:
        return "failed"
    if link.status in {
        LinkStatus.READY_FOR_LIVE_TEST,
        LinkStatus.PENDING_USER_VALIDATION,
        LinkStatus.LIVE_TEST_RUNNING,
    }:
        return "ready_for_test"
    return "unknown"


def _chat_message(binding_status: str, health_status: str) -> str:
    if binding_status != "bound":
        return {
            "pending": "尚未绑定",
            "conflict": "绑定存在冲突",
            "expired": "绑定已过期",
        }.get(binding_status, "绑定状态待确认")
    return {
        "live_verified": "已验证",
        "ready_for_test": "已绑定，等待聊天验证",
        "failed": "聊天验证失败，不会自动重发",
        "stale": "之前验证过，环境已变化，需要重新确认",
        "unknown": "已绑定，聊天状态待确认",
    }[health_status]


def _chat_links(state: Any, binding: OnboardingBindingSnapshot) -> list[ChatLinkSnapshot]:
    try:
        links = state.observability.list_links()
    except Exception:
        links = [
            LinkState(
                link_id=link_id,
                bot_slot=link_id.bot_slot,
                session_scope=link_id.session_scope,
            )
            for link_id in LinkId
        ]
    snapshots: list[ChatLinkSnapshot] = []
    for link in links:
        binding_status = _binding_status(binding, link)
        health_status = _chat_health_status(link)
        snapshots.append(
            ChatLinkSnapshot(
                link_id=link.link_id.value,
                slot=cast(Slot, link.bot_slot),
                scope=link.session_scope,
                binding_status=cast(Any, binding_status),
                health_status=cast(Any, health_status),
                user_message=_chat_message(binding_status, health_status),
                evidence_level=link.evidence_level.value,
                diagnostic_code=link.diagnostic_code,
                correlation_id=link.correlation_id,
                request_message_id=link.request_message_id,
                response_message_id=link.response_message_id,
                latency_ms=link.latency_ms,
            )
        )
    return snapshots


def _overall_chat_health(links: list[ChatLinkSnapshot]) -> str:
    values = {link.health_status for link in links}
    if values == {"live_verified"}:
        return "live_verified"
    if "stale" in values:
        return "stale"
    if "failed" in values:
        return "failed"
    if links and values <= {"ready_for_test", "live_verified"}:
        return "ready_for_test"
    return "unknown"


def _cc_switch(state: Any) -> tuple[bool | None, bool]:
    try:
        status = state.cc_switch.detect()
    except Exception:
        return None, False
    installed = status.installation_status == "installed"
    return installed, installed and bool(status.executable_path)


def _snapshot(state: Any, *, refresh_agents: bool = False) -> OnboardingSnapshot:
    observed = _now()
    binding = _binding_snapshot(state)
    detections = state.agent_detection.get_all(refresh=refresh_agents)
    runtime = _runtime_readiness(state)
    agents = _agent_snapshots(
        state,
        binding,
        detections,
        runtime_ready=runtime.ready,
    )
    private_count = binding.bound_private_count
    group_count = binding.bound_group_count
    tokens = sum(item.token_ready for item in agents)
    identities_verified = sum(item.identity_verified for item in agents)
    native_ready, native_revision = _native_configuration_ready(state)
    agents_ready = all(item.acceptable for item in agents)
    chat_links = _chat_links(state, binding)
    chat_health = _overall_chat_health(chat_links)
    cc_switch_installed, cc_switch_openable = _cc_switch(state)

    if tokens < 3 or identities_verified < 3:
        current_step = 1
    elif private_count < 3:
        current_step = 2
    elif group_count < 3:
        current_step = 3
    else:
        current_step = 4
    complete = bool(
        binding.state == "completed" and agents_ready and native_ready and runtime.ready
    )

    if agents_ready:
        agent_message = "Hermes、Claude Code 和 Codex 均已检测到"
        agent_status = "complete"
    else:
        missing = [item.display_name for item in agents if not item.acceptable]
        agent_message = "需要处理：" + "、".join(missing)
        agent_status = "needs_action"
    checklist = [
        OnboardingChecklistItem(
            key="telegram",
            label="检查 Telegram 连接",
            status="complete" if tokens == 3 and identities_verified == 3 else "needs_action",
            user_message=(
                "Telegram Bot 身份已准备好"
                if tokens == 3 and identities_verified == 3
                else "还需要录入并验证 3 个 Bot Token"
            ),
        ),
        OnboardingChecklistItem(
            key="agents",
            label="检查 Hermes、Claude Code 和 Codex",
            status=cast(Any, agent_status),
            user_message=agent_message,
        ),
        OnboardingChecklistItem(
            key="runtime",
            label="准备运行环境",
            status=(
                "complete" if runtime.ready else ("needs_action" if group_count == 3 else "pending")
            ),
            user_message=runtime.user_message,
        ),
        OnboardingChecklistItem(
            key="configuration",
            label="生成连接配置",
            status=(
                "complete" if native_ready else ("needs_action" if group_count == 3 else "pending")
            ),
            user_message=(
                f"连接配置版本 {native_revision} 已验证"
                if native_ready
                else "绑定完成后生成并验证连接配置"
            ),
        ),
        OnboardingChecklistItem(
            key="chat",
            label="检查聊天是否可用",
            status=(
                "complete"
                if chat_health == "live_verified"
                else ("needs_action" if complete else "pending")
            ),
            user_message={
                "live_verified": "六条聊天链路均已通过当前环境的真实验证",
                "ready_for_test": "基础配置已完成，可以选择快速验证聊天",
                "failed": "聊天验证失败，不会自动重发测试消息",
                "stale": "历史聊天证据已失效，需要重新确认",
                "unknown": "聊天健康尚未验证",
            }[chat_health],
        ),
    ]
    overall: Literal["ready", "needs_action", "pending", "degraded"] = (
        "ready" if complete else "needs_action"
    )
    revision_parts = "-".join(detections[slot].revision[-8:] for slot in SLOTS)
    return OnboardingSnapshot(
        revision=(
            f"onboarding-{binding.revision}-{native_revision}-{runtime.configuration_revision}-"
            f"{revision_parts}-{observed.timestamp():.0f}"
        ),
        observed_at=observed,
        current_step=current_step,
        onboarding_complete=complete,
        agents=agents,
        binding=binding,
        checklist=checklist,
        runtime=runtime,
        chat_health=cast(Any, chat_health),
        chat_links=chat_links,
        cc_switch_installed=cc_switch_installed,
        cc_switch_openable=cc_switch_openable,
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
    def onboarding_snapshot(
        refresh_agents: bool = Query(default=False),
        _token: str = Depends(bearer_auth),
    ):
        return redact_value(
            _snapshot(get_state(), refresh_agents=refresh_agents).model_dump(mode="json")
        )

    @router.get("/agents", response_model=list[AgentDetectionSnapshot])
    def list_agents(
        refresh: bool = Query(default=False),
        _token: str = Depends(bearer_auth),
    ):
        return redact_value(
            [
                item.model_dump(mode="json")
                for item in get_state().agent_detection.public_snapshots(refresh=refresh)
            ]
        )

    @router.get("/dashboard/snapshot", response_model=DashboardSnapshot)
    def dashboard_snapshot(
        refresh_agents: bool = Query(default=False),
        _token: str = Depends(bearer_auth),
    ):
        snapshot = _snapshot(get_state(), refresh_agents=refresh_agents)
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
                runtime=snapshot.runtime,
                chat_health=snapshot.chat_health,
                agents=[
                    DashboardAgentSnapshot(
                        slot=item.slot,
                        display_name=item.display_name,
                        installed=item.installed,
                        connected=item.connected,
                        version=item.version,
                        detection_status=item.detection_status,
                        probe_status=item.probe_status,
                        official_install_url=item.official_install_url,
                        status=(
                            "ready"
                            if item.acceptable
                            else ("needs_action" if item.installed is not None else "unknown")
                        ),
                        user_message=item.user_message,
                    )
                    for item in snapshot.agents
                ],
                chat_links=snapshot.chat_links,
                chat_pills=[item.user_message for item in snapshot.chat_links],
                cc_switch_installed=snapshot.cc_switch_installed,
                cc_switch_openable=snapshot.cc_switch_openable,
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

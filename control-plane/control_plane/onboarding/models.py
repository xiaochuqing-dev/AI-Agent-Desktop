from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Slot = Literal["hermes", "claude", "codex"]
StepStatus = Literal["pending", "active", "complete", "needs_action", "failed"]


class OnboardingAgentSnapshot(StrictModel):
    slot: Slot
    display_name: str
    bot_username: str | None = None
    bot_id: int | None = None
    token_ready: bool = False
    identity_verified: bool = False
    installed: bool | None = None
    connected: bool | None = None
    version: str | None = None
    detection_status: Literal[
        "installed",
        "not_found",
        "found_but_unhealthy",
        "version_unknown",
        "detection_error",
    ] = "detection_error"
    probe_status: Literal[
        "not_run", "healthy", "version_unknown", "failed", "timeout", "launch_error"
    ] = "not_run"
    detection_source: Literal["path", "known_location", "not_found", "error"] = "error"
    diagnostic_code: str | None = None
    official_install_url: str
    acceptable: bool = False
    private_status: Literal["pending", "bound", "rejected"] = "pending"
    group_status: Literal["pending", "bound", "rejected"] = "pending"
    user_message: str


class OnboardingBindingSnapshot(StrictModel):
    session_id: str | None = None
    state: str = "not_started"
    expires_at: datetime | None = None
    bound_private_count: int = Field(default=0, ge=0, le=3)
    bound_group_count: int = Field(default=0, ge=0, le=3)
    group_title: str | None = None
    group_type: Literal["group", "supergroup"] | None = None
    revision: int = Field(default=0, ge=0)


class OnboardingChecklistItem(StrictModel):
    key: str
    label: str
    status: StepStatus
    user_message: str


class RuntimeReadinessSnapshot(StrictModel):
    ready: bool = False
    observed_state: str = "unknown"
    pid_verified: bool = False
    executable_verified: bool = False
    configuration_revision_verified: bool = False
    port_owned_by_process: bool = False
    startup_stable_for_window: bool = False
    configuration_revision: int = Field(default=0, ge=0)
    diagnostic_code: str | None = None
    user_message: str


class ChatLinkSnapshot(StrictModel):
    link_id: str
    slot: Slot
    scope: Literal["private", "group"]
    binding_status: Literal["pending", "bound", "conflict", "expired"]
    health_status: Literal["unknown", "ready_for_test", "live_verified", "failed", "stale"]
    user_message: str
    evidence_level: str = "inferred"
    diagnostic_code: str | None = None
    correlation_id: str | None = None
    request_message_id: int | None = None
    response_message_id: int | None = None
    latency_ms: int | None = None


class TelegramClientAvailability(StrictModel):
    tg_handler_available: bool
    https_deep_link_available: bool = True
    checked_at: datetime
    official_download_url: str = "https://desktop.telegram.org/"


class OnboardingSnapshot(StrictModel):
    revision: str
    observed_at: datetime
    current_step: int = Field(default=0, ge=0, le=4)
    onboarding_complete: bool = False
    agents: list[OnboardingAgentSnapshot]
    binding: OnboardingBindingSnapshot
    checklist: list[OnboardingChecklistItem]
    runtime: RuntimeReadinessSnapshot
    chat_health: Literal["unknown", "ready_for_test", "live_verified", "failed", "stale"]
    chat_links: list[ChatLinkSnapshot]
    cc_switch_installed: bool | None = None
    cc_switch_openable: bool = False
    telegram_client: TelegramClientAvailability
    overall_status: Literal["ready", "needs_action", "pending", "degraded"]


class DashboardAgentSnapshot(StrictModel):
    slot: Slot
    display_name: str
    installed: bool | None = None
    connected: bool | None = None
    version: str | None = None
    detection_status: Literal[
        "installed",
        "not_found",
        "found_but_unhealthy",
        "version_unknown",
        "detection_error",
    ]
    probe_status: str
    official_install_url: str
    status: Literal["ready", "needs_action", "unknown"]
    user_message: str


class DashboardSnapshot(StrictModel):
    revision: str
    observed_at: datetime
    overall_status: Literal["ready", "needs_action", "pending", "degraded"]
    telegram_status: Literal["ready", "needs_action", "unknown"]
    runtime: RuntimeReadinessSnapshot
    chat_health: Literal["unknown", "ready_for_test", "live_verified", "failed", "stale"]
    agents: list[DashboardAgentSnapshot]
    chat_links: list[ChatLinkSnapshot]
    chat_pills: list[str]
    cc_switch_installed: bool | None = None
    cc_switch_openable: bool = False
    recent_issues: list[str]

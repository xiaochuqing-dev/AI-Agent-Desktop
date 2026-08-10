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
    telegram_client: TelegramClientAvailability
    overall_status: Literal["ready", "needs_action", "pending", "degraded"]


class DashboardAgentSnapshot(StrictModel):
    slot: Slot
    display_name: str
    installed: bool | None = None
    connected: bool | None = None
    status: Literal["ready", "needs_action", "unknown"]
    user_message: str


class DashboardSnapshot(StrictModel):
    revision: str
    observed_at: datetime
    overall_status: Literal["ready", "needs_action", "pending", "degraded"]
    telegram_status: Literal["ready", "needs_action", "unknown"]
    agents: list[DashboardAgentSnapshot]
    chat_pills: list[str]
    recent_issues: list[str]

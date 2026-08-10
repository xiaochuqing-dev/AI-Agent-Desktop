from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


TelegramBotSlot = Literal["hermes", "claude", "codex"]


class TelegramBotIdentity(StrictModel):
    slot: TelegramBotSlot
    bot_id: int = Field(gt=0)
    username: str = Field(min_length=1, max_length=128)
    first_name: str = Field(min_length=1, max_length=256)
    can_join_groups: bool
    can_read_all_group_messages: bool
    credential_reference_id: str
    credential_revision: int = Field(ge=1)
    verified_at: datetime
    verification_status: Literal["verified", "invalid", "unknown"]


class TelegramWebhookInfo(StrictModel):
    url_present: bool
    has_custom_certificate: bool = False
    pending_update_count: int = Field(default=0, ge=0)
    last_error_date: int | None = None
    last_error_message_present: bool = False
    max_connections: int | None = None
    allowed_updates: list[str] = Field(default_factory=list)


class TelegramUpdate(StrictModel):
    update_id: int = Field(ge=0)
    payload: dict[str, Any]


class UpdateOwner(StrEnum):
    NONE = "none"
    CONTROL_PLANE_BINDING = "control_plane_binding"
    HERMES_RUNTIME = "hermes_runtime"
    CC_CONNECT_RUNTIME = "cc_connect_runtime"
    EXTERNAL = "external"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class TelegramUpdateLease(StrictModel):
    bot_slot: TelegramBotSlot
    owner: UpdateOwner
    operation_id: str | None = None
    credential_revision: int = Field(default=0, ge=0)
    acquired_at: datetime | None = None
    expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    offset: int = Field(default=0, ge=0)
    release_reason: str | None = None
    revision: int = Field(default=0, ge=0)


class TelegramGroupVerification(StrictModel):
    slot: TelegramBotSlot
    group_title: str | None = None
    group_type: Literal["group", "supergroup"]
    bot_status: Literal[
        "creator", "administrator", "member", "restricted", "left", "kicked", "unknown"
    ]
    can_send_messages: bool | None = None
    privacy_mode_warning: bool
    user_message: str


class BindingState(StrEnum):
    CREATED = "created"
    CREDENTIALS_VERIFIED = "credentials_verified"
    WAITING_PRIVATE = "waiting_private"
    PRIVATE_VERIFIED = "private_verified"
    WAITING_GROUP = "waiting_group"
    PARTIALLY_BOUND = "partially_bound"
    GROUP_CONSISTENCY_PENDING = "group_consistency_pending"
    COMPLETED = "completed"
    CANCELED = "canceled"
    EXPIRED = "expired"
    CONFLICT = "conflict"
    FAILED = "failed"


class BindingSlotProgress(StrictModel):
    slot: TelegramBotSlot
    bot_id: int
    username: str
    private_status: Literal["pending", "bound", "rejected"] = "pending"
    group_status: Literal["pending", "bound", "rejected"] = "pending"
    private_user_id: int | None = None
    group_chat_id: int | None = None
    group_title: str | None = None
    group_type: Literal["group", "supergroup"] | None = None
    last_update_id: int | None = None


class BindingSession(StrictModel):
    session_id: str
    state: BindingState
    expires_at: datetime
    operator_user_id: int | None = None
    group_chat_id: int | None = None
    group_title: str | None = None
    group_type: Literal["group", "supergroup"] | None = None
    slots: list[BindingSlotProgress]
    bound_private_count: int = Field(ge=0, le=3)
    bound_group_count: int = Field(ge=0, le=3)
    revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class BindingSessionCreated(BindingSession):
    bind_code: str = Field(
        min_length=8,
        max_length=64,
        json_schema_extra={"writeOnly": True, "x-display-once": True},
    )
    private_deep_links: dict[TelegramBotSlot, str]
    group_deep_links: dict[TelegramBotSlot, str]
    private_commands: dict[TelegramBotSlot, str]
    group_commands: dict[TelegramBotSlot, str]


class BindingCreateRequest(StrictModel):
    expires_in_seconds: int = Field(default=900, ge=120, le=1800)
    runtimes_stopped_confirmation: Literal[True]


class BindingResumeRequest(StrictModel):
    expires_in_seconds: int = Field(default=900, ge=120, le=1800)
    runtimes_stopped_confirmation: Literal[True]


class BindingPollRequest(StrictModel):
    timeout_seconds: int = Field(default=10, ge=0, le=25)


class BindingCancelRequest(StrictModel):
    confirmation: Literal[True]
    reason: str = Field(default="user_canceled", min_length=1, max_length=128)


class WebhookDeleteRequest(StrictModel):
    explicit_confirmation: Literal[True]
    drop_pending_updates: bool = False

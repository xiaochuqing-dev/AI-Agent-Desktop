from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LinkId(StrEnum):
    HERMES_PRIVATE = "hermes.private"
    HERMES_GROUP = "hermes.group"
    CLAUDE_PRIVATE = "claude.private"
    CLAUDE_GROUP = "claude.group"
    CODEX_PRIVATE = "codex.private"
    CODEX_GROUP = "codex.group"

    @property
    def bot_slot(self) -> Literal["hermes", "claude", "codex"]:
        return self.value.split(".", 1)[0]  # type: ignore[return-value]

    @property
    def session_scope(self) -> Literal["private", "group"]:
        return self.value.split(".", 1)[1]  # type: ignore[return-value]


ALL_LINK_IDS: tuple[LinkId, ...] = tuple(LinkId)


class LinkStatus(StrEnum):
    UNKNOWN = "unknown"
    NOT_CONFIGURED = "not_configured"
    CREDENTIAL_MISSING = "credential_missing"
    IDENTITY_UNVERIFIED = "identity_unverified"
    BINDING_PENDING = "binding_pending"
    RUNTIME_STOPPED = "runtime_stopped"
    RUNTIME_CONFLICT = "runtime_conflict"
    READY_FOR_LIVE_TEST = "ready_for_live_test"
    LIVE_TEST_RUNNING = "live_test_running"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    PENDING_USER_VALIDATION = "pending_user_validation"


class EvidenceLevel(StrEnum):
    INFERRED = "inferred"
    SYNTHETIC = "synthetic"
    OBSERVED = "observed"
    LIVE_VERIFIED = "live_verified"


class TestLifecycle(StrEnum):
    PLANNED = "planned"
    CONFIRMED = "confirmed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELED = "canceled"
    EXPIRED = "expired"


class LinkState(StrictModel):
    link_id: LinkId
    bot_slot: Literal["hermes", "claude", "codex"]
    session_scope: Literal["private", "group"]
    bot_id: int | None = Field(default=None, gt=0)
    bot_username: str | None = None
    credential_reference_id: str | None = None
    credential_revision: int = Field(default=0, ge=0)
    binding_session_id: str | None = None
    binding_revision: int = Field(default=0, ge=0)
    operator_identity_hash: str | None = None
    group_identity_hash: str | None = None
    runtime_owner: str = "unknown"
    runtime_state: str = "unknown"
    configuration_revision: int = Field(default=0, ge=0)
    update_lease_owner: str = "unknown"
    send_status: str = "unknown"
    receive_status: str = "unknown"
    response_status: str = "unknown"
    correlation_id: str | None = None
    request_message_id: int | None = Field(default=None, ge=0)
    response_message_id: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    evidence_level: EvidenceLevel = EvidenceLevel.INFERRED
    status: LinkStatus = LinkStatus.UNKNOWN
    diagnostic_code: str | None = None
    recovery_actions: list[str] = Field(default_factory=list)
    last_probe_at: datetime | None = None
    last_live_verified_at: datetime | None = None


class E2ETestPlan(StrictModel):
    plan_id: str
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    link_id: LinkId
    target_bot_slot: Literal["hermes", "claude", "codex"]
    expected_bot_id: int = Field(gt=0)
    target_chat_kind: Literal["private", "group"]
    target_chat_identity_hash: str
    expected_credential_revision: int = Field(ge=1)
    expected_binding_session_id: str
    expected_binding_revision: int = Field(ge=1)
    expected_configuration_revision: int = Field(default=0, ge=0)
    expected_runtime_owner: str
    expected_runtime_state: str
    expected_update_lease_owner: str
    correlation_id: str
    payload_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    message_count: Literal[1] = 1
    automatic_retry: Literal[False] = False
    expires_at: datetime
    explicit_confirmation_required: Literal[True] = True
    status: TestLifecycle = TestLifecycle.PLANNED
    created_at: datetime


class E2ETestConfirmation(StrictModel):
    plan_id: str
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    link_id: LinkId
    credential_revision: int = Field(ge=1)
    binding_session_id: str
    binding_revision: int = Field(ge=1)
    configuration_revision: int = Field(default=0, ge=0)
    confirmation: Literal[True]


class E2ETestRun(StrictModel):
    run_id: str
    plan_id: str
    link_id: LinkId
    lifecycle: TestLifecycle
    evidence_level: EvidenceLevel
    correlation_id: str
    request_message_id: int | None = Field(default=None, ge=0)
    response_message_id: int | None = Field(default=None, ge=0)
    reply_to_message_id: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)
    diagnostic_code: str | None = None
    recovery_actions: list[str] = Field(default_factory=list)
    message_count: Literal[1] = 1
    automatic_retry: Literal[False] = False
    created_at: datetime
    completed_at: datetime | None = None


class E2ETestResponseEvidence(StrictModel):
    """Runtime-supplied response identifiers; message bodies are never accepted."""

    run_id: str
    bot_id: int = Field(gt=0)
    chat_identity_hash: str
    response_message_id: int = Field(gt=0)
    reply_to_message_id: int | None = Field(default=None, gt=0)
    received_at: datetime | None = None


class MessageCorrelation(StrictModel):
    correlation_id: str
    link_id: LinkId
    bot_id: int = Field(gt=0)
    chat_identity_hash: str
    request_message_id: int = Field(ge=0)
    response_message_id: int | None = Field(default=None, ge=0)
    reply_to_message_id: int | None = Field(default=None, ge=0)
    send_status: Literal["sent", "failed", "unknown"]
    response_status: Literal["received", "missing", "ambiguous", "duplicate", "unknown"]
    sent_at: datetime
    responded_at: datetime | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    diagnostic_code: str | None = None


class IsolationCheck(StrictModel):
    name: str
    status: Literal["passed", "failed", "unknown"]
    evidence: dict[str, Any] = Field(default_factory=dict)
    diagnostic_code: str | None = None


class SessionIsolationResult(StrictModel):
    probe_id: str
    status: Literal["passed", "failed", "unknown"]
    evidence_level: EvidenceLevel
    checks: list[IsolationCheck]
    created_at: datetime
    completed_at: datetime | None = None


class ProxyPolicyState(StrictModel):
    mode: Literal["direct", "environment", "explicit"]
    source: Literal["none", "environment", "explicit"]
    effective_proxy: str | None = None
    credential_reference_id: str | None = None
    status: Literal["ready", "missing", "invalid", "authentication_failed", "timeout", "unknown"]
    diagnostic_code: str | None = None

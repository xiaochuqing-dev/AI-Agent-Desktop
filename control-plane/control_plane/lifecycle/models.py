from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..configuration.models import LifecycleOwner, ManagementOwner


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LifecycleActionRequest(StrictModel):
    configuration_revision: int = Field(ge=1)
    confirmation: Literal[True]


class OwnershipPlanRequest(StrictModel):
    target_lifecycle_owner: Literal[LifecycleOwner.PRODUCT] = LifecycleOwner.PRODUCT
    expires_in_seconds: int = Field(default=900, ge=60, le=3600)


class OwnershipPlan(StrictModel):
    plan_id: str
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    context_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    component_id: Literal["cc-connect"] = "cc-connect"
    artifact_id: str
    current_management_owner: ManagementOwner
    target_management_owner: Literal[ManagementOwner.PRODUCT] = ManagementOwner.PRODUCT
    current_lifecycle_owner: LifecycleOwner
    target_lifecycle_owner: Literal[LifecycleOwner.PRODUCT] = LifecycleOwner.PRODUCT
    external_process_detected: bool
    expected_changes: list[str]
    risk: Literal["medium"] = "medium"
    rollback_plan: list[str]
    user_confirmation_required: Literal[True] = True
    created_at: datetime
    expires_at: datetime


class OwnershipConfirmationRequest(StrictModel):
    plan_id: str
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    current_management_owner: ManagementOwner
    current_lifecycle_owner: LifecycleOwner
    confirmation: Literal[True]


class ProcessIdentity(StrictModel):
    component_id: Literal["cc-connect"] = "cc-connect"
    product_instance_id: str
    artifact_id: str
    executable_path: str
    executable_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    pid: int = Field(gt=0)
    process_create_time: str
    parent_pid: int
    start_command_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    configuration_revision: int = Field(ge=1)
    listen_host: Literal["127.0.0.1"] = "127.0.0.1"
    listen_port: int = Field(ge=59000, le=59999)
    lifecycle_owner: Literal[LifecycleOwner.PRODUCT] = LifecycleOwner.PRODUCT
    operation_id: str


class IdentityVerification(StrictModel):
    status: Literal["verified", "missing", "pid_reused", "mismatch", "inaccessible"]
    checks: dict[str, bool | str]
    diagnostic_code: str | None = None


class PortOwnershipEvidence(StrictModel):
    listen_host: Literal["127.0.0.1"] = "127.0.0.1"
    listen_port: int = Field(ge=59000, le=59999)
    status: Literal["free", "owned", "conflict", "not_listening", "unknown"]
    owner_pid: int | None = None
    expected_pid: int | None = None
    ipv6_status: Literal["unsupported", "unknown"] = "unknown"
    evidence: dict[str, Any] = Field(default_factory=dict)


class RuntimeHealth(StrictModel):
    overall: Literal["stopped", "starting", "partial", "unhealthy", "unknown"]
    process_identity_verified: bool
    artifact_integrity_verified: bool
    configuration_revision_verified: bool
    port_owned_by_process: bool
    startup_stable_for_window: bool
    local_endpoint_verified: Literal[False] = False
    local_endpoint_status: Literal["unsupported"] = "unsupported"
    deep_health: Literal["unsupported"] = "unsupported"
    fatal_log_detected: bool = False
    management_api_verified: bool = False
    management_api_status: Literal[
        "not_checked", "verified", "auth_failed", "unreachable", "unsupported"
    ] = "not_checked"
    management_api_bind_scope: Literal["upstream_all_interfaces", "unknown"] = "unknown"


class LifecycleRuntimeStatus(StrictModel):
    component_id: Literal["cc-connect"] = "cc-connect"
    product_instance_id: str | None = None
    artifact_id: str | None = None
    configuration_revision: int = Field(default=0, ge=0)
    expected_state: Literal["running", "stopped"]
    observed_state: Literal[
        "unconfigured",
        "stopped",
        "starting",
        "running_partial",
        "crashed",
        "conflict",
        "unknown",
    ]
    management_owner: ManagementOwner
    lifecycle_owner: LifecycleOwner
    pid: int | None = None
    identity: ProcessIdentity | None = None
    identity_verification: IdentityVerification | None = None
    port_ownership: PortOwnershipEvidence | None = None
    health: RuntimeHealth
    last_exit_code: int | None = None
    updated_at: datetime

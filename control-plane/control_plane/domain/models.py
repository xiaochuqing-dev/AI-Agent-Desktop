# 领域模型,镜像 contracts/control-plane-v1/core-models.schema.json 的切片相关子集。
# 字段名与契约 snake_case 一致;extra=forbid 对应 schema 的 additionalProperties:false。
# 本文件只定义结构,不含任何 Secret 明文,也不读取真实运行环境。
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelConfig(BaseModel):
    # 统一配置:禁止额外字段(匹配 additionalProperties:false),字段按名填充。
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# 六类正交状态枚举(对应 core-models InstallationState 等)
class InstallationState(str, Enum):
    UNKNOWN = "unknown"
    NOT_INSTALLED = "not_installed"
    INSTALLING = "installing"
    INSTALLED = "installed"
    UNINSTALLING = "uninstalling"
    FAILED = "failed"


class ConfigurationState(str, Enum):
    UNKNOWN = "unknown"
    MISSING = "missing"
    VALIDATING = "validating"
    VALID = "valid"
    INVALID = "invalid"
    CONFLICT = "conflict"


class AuthenticationState(str, Enum):
    UNKNOWN = "unknown"
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    EXPIRED = "expired"
    INVALID = "invalid"


class RuntimeState(str, Enum):
    UNKNOWN = "unknown"
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    RESTARTING = "restarting"
    FAILED = "failed"


class HealthState(str, Enum):
    UNKNOWN = "unknown"
    CHECKING = "checking"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class UpdateState(str, Enum):
    UNKNOWN = "unknown"
    CHECKING = "checking"
    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    UPDATING = "updating"
    ROLLBACK_AVAILABLE = "rollback_available"
    ROLLING_BACK = "rolling_back"
    FAILED = "failed"


class UserStatus(str, Enum):
    NOT_INSTALLED = "not_installed"
    INSTALLED_UNCONFIGURED = "installed_unconfigured"
    LOGIN_REQUIRED = "login_required"
    CONFIGURATION_INVALID = "configuration_invalid"
    STARTING = "starting"
    RUNNING_HEALTHY = "running_healthy"
    PARTIALLY_DEGRADED = "partially_degraded"
    UPDATE_AVAILABLE = "update_available"
    START_FAILED = "start_failed"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


class StatusOverlay(str, Enum):
    UPDATE_AVAILABLE = "update_available"
    OPERATION_IN_PROGRESS = "operation_in_progress"
    DRIFT_DETECTED = "drift_detected"
    RESTART_REQUIRED = "restart_required"


class ConditionStatus(str, Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class CapabilityMaturity(str, Enum):
    STABLE = "stable"
    EXPERIMENTAL = "experimental"
    DEPRECATED = "deprecated"


class CapabilityAvailability(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class OperationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class DiagnosticSeverity(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ManagementOwnerType(str, Enum):
    APPLICATION = "application"
    OFFICIAL_LOGIN = "official_login"
    CC_SWITCH = "cc_switch"
    EXTERNAL = "external"


class ManagementOwnerState(str, Enum):
    UNASSIGNED = "unassigned"
    OWNED = "owned"
    TRANSFER_PREPARING = "transfer_preparing"
    TRANSFER_COMMITTING = "transfer_committing"
    CONFLICT = "conflict"


class DryRunActionType(str, Enum):
    INSTALL = "install"
    CONFIGURE = "configure"
    AUTHENTICATE = "authenticate"
    START = "start"
    STOP = "stop"
    RESTART = "restart"
    UPDATE = "update"
    ROLLBACK = "rollback"
    TRANSFER_OWNER = "transfer_owner"
    MIGRATE = "migrate"


class EstimatedRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CredentialStatus(str, Enum):
    UNKNOWN = "unknown"
    STORED = "stored"
    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"
    UNAVAILABLE = "unavailable"


class ResourceRef(ModelConfig):
    kind: str = Field(min_length=1, max_length=64)
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class Condition(ModelConfig):
    type: str = Field(min_length=1, max_length=128)
    status: ConditionStatus
    reason: str = Field(min_length=1, max_length=128)
    message: str = Field(max_length=2048)
    observed_generation: int = Field(ge=0)
    last_transition_time: datetime


class Capability(ModelConfig):
    capability_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
    maturity: CapabilityMaturity
    availability: CapabilityAvailability
    constraints: dict[str, Any] = Field(default_factory=dict)


class StateSnapshot(ModelConfig):
    installation: InstallationState
    configuration: ConfigurationState
    authentication: AuthenticationState
    runtime: RuntimeState
    health: HealthState
    update: UpdateState
    user_status: UserStatus
    status_overlays: list[StatusOverlay] = Field(default_factory=list)
    conditions: list[Condition] = Field(default_factory=list)
    generation: int = Field(ge=0)
    observed_generation: int = Field(ge=0)
    revision: str = Field(min_length=1, max_length=128)
    observed_at: datetime


class Component(ModelConfig):
    component_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    kind: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=256)
    version: str | None = Field(default=None, max_length=128)
    state: StateSnapshot
    provider_refs: list[str] = Field(default_factory=list)


class OperationProgress(ModelConfig):
    phase: str = Field(min_length=1, max_length=128)
    percent: float | None = Field(default=None, ge=0, le=100)
    message: str = Field(max_length=2048)
    completed_units: int = Field(ge=0)
    total_units: int | None = Field(default=None, ge=0)
    point_of_no_return: bool


class UserFacingError(ModelConfig):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    message: str = Field(min_length=1, max_length=2048)
    retryable: bool
    recovery_actions: list[str] = Field(default_factory=list)
    diagnostic_id: str | None = Field(default=None, max_length=128)
    operation_id: str | None = Field(default=None, max_length=128)


class Operation(ModelConfig):
    operation_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    kind: str = Field(min_length=1, max_length=128)
    target_ref: ResourceRef
    status: OperationStatus
    progress: OperationProgress
    result: dict[str, Any] | None = None
    error: UserFacingError | None = None
    idempotency_key: str = Field(min_length=16, max_length=256)
    deadline_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class Diagnostic(ModelConfig):
    diagnostic_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    severity: DiagnosticSeverity
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    summary: str = Field(min_length=1, max_length=512)
    user_message: str = Field(min_length=1, max_length=2048)
    suggested_actions: list[str] = Field(default_factory=list)
    technical_details: dict[str, Any] = Field(default_factory=dict)
    redaction_applied: bool = True
    created_at: datetime
    correlation_id: str = Field(min_length=1, max_length=128)
    operation_id: str | None = Field(default=None, max_length=128)
    target_ref: ResourceRef | None = None


class SystemInfo(ModelConfig):
    instance_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    api_version: str = "v1"
    contract_version: str
    service_version: str
    started_at: datetime
    epoch: str = Field(min_length=1, max_length=128)


class DryRunAction(ModelConfig):
    action_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    component_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    action_type: DryRunActionType
    reason: str = Field(min_length=1, max_length=512)
    prerequisites: list[str] = Field(default_factory=list)
    requires_admin: bool
    requires_user_interaction: bool
    secret_required: bool
    estimated_risk: EstimatedRisk
    reversible: bool
    rollback_hint: str = Field(max_length=1024)
    status: str = "planned"


class DryRunPlan(ModelConfig):
    # dry-run 计划:只生成不执行。首片 execute 恒为 false,status 恒为 planned。
    plan_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    operation_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    execute: bool = False
    status: str = "planned"
    actions: list[DryRunAction] = Field(min_length=1)
    generated_at: datetime


class SecretRef(ModelConfig):
    # 对已存 Secret 的引用:永不承载值,只判断存在性或可访问性。
    secret_ref_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    credential_ref: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    purpose: str = Field(min_length=1, max_length=128)
    owner: str = Field(min_length=1, max_length=128)
    backend: str = Field(min_length=1, max_length=128)
    status: CredentialStatus
    exists: bool | None = None
    redacted: bool = True


class ReadinessReport(ModelConfig):
    # 一次就绪扫描的聚合只读报告。不含 Secret;声明本次扫描未修改系统。
    report_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    scan_operation_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    user_summary: str = Field(min_length=1, max_length=2048)
    components: list[Component] = Field(default_factory=list)
    blockers: list[Diagnostic] = Field(default_factory=list)
    warnings: list[Diagnostic] = Field(default_factory=list)
    ready_items: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    estimated_next_steps: list[str] = Field(default_factory=list)
    dry_run_plan: DryRunPlan
    evidence_sources: list[str] = Field(default_factory=list)
    scanned_at: datetime
    scan_version: str = Field(min_length=1, max_length=128)
    system_modified: bool = False
    redaction_applied: bool = True


class CredentialMetadata(ModelConfig):
    # 只读凭据元数据,不含值。首片不实现写入。
    credential_ref: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    purpose: str = Field(min_length=1, max_length=128)
    owner: str = Field(min_length=1, max_length=128)
    backend: str = Field(min_length=1, max_length=128)
    status: CredentialStatus
    revision: str = Field(min_length=1, max_length=128)
    created_at: datetime
    updated_at: datetime
    last_validated_at: datetime | None = None
    expires_at: datetime | None = None

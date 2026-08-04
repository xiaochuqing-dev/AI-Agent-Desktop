from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManagementOwner(StrEnum):
    EXTERNAL = "external"
    PRODUCT = "product"
    UNMANAGED = "unmanaged"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class LifecycleOwner(StrEnum):
    EXTERNAL = "external"
    PRODUCT = "product"
    NONE = "none"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class SecretStatus(StrEnum):
    MISSING = "missing"
    AVAILABLE = "available"
    INACCESSIBLE = "inaccessible"
    UNKNOWN = "unknown"


class SecretReference(StrictModel):
    reference_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,63}$")
    backend: Literal["windows_credential_manager", "memory"]
    purpose: Literal["telegram_bot_token", "agent_api_key"]
    required: bool


class TelegramConfiguration(StrictModel):
    enabled: Literal[False] = False
    mode: Literal["disabled"] = "disabled"


class HealthProbeConfiguration(StrictModel):
    startup_timeout_seconds: int = Field(default=10, ge=1, le=120)
    stable_window_seconds: int = Field(default=3, ge=1, le=60)
    local_endpoint_supported: Literal[False] = False
    deep_health: Literal["unsupported"] = "unsupported"


class ManagedConfiguration(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    component_id: Literal["cc-connect"] = "cc-connect"
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    product_instance_id: str = Field(pattern=r"^instance-[a-f0-9]{24}$")
    listen_host: Literal["127.0.0.1"] = "127.0.0.1"
    listen_port: int = Field(ge=59000, le=59999)
    data_dir: str = Field(min_length=1, max_length=1024)
    log_dir: str = Field(min_length=1, max_length=1024)
    project_root: str = Field(min_length=1, max_length=1024)
    lifecycle_owner: LifecycleOwner
    management_owner: ManagementOwner
    configuration_revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    secret_refs: list[SecretReference]
    telegram: TelegramConfiguration = Field(default_factory=TelegramConfiguration)
    network_mode: Literal["loopback_only"] = "loopback_only"
    health_probe: HealthProbeConfiguration = Field(default_factory=HealthProbeConfiguration)

    @model_validator(mode="after")
    def validate_product_owned_scope(self) -> ManagedConfiguration:
        if self.lifecycle_owner != LifecycleOwner.PRODUCT:
            raise ValueError("managed configuration requires product lifecycle ownership")
        if self.management_owner != ManagementOwner.PRODUCT:
            raise ValueError("managed configuration requires product management ownership")
        if len({item.reference_id for item in self.secret_refs}) != len(self.secret_refs):
            raise ValueError("secret reference identifiers must be unique")
        return self


class ConfigurationPlanRequest(StrictModel):
    listen_port: int | None = Field(default=None, ge=59000, le=59999)
    expires_in_seconds: int = Field(default=900, ge=60, le=3600)
    rollback_to_revision: int | None = Field(default=None, ge=1)


class ConfigurationPlan(StrictModel):
    plan_id: str
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    context_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    component_id: Literal["cc-connect"] = "cc-connect"
    artifact_id: str
    current_revision: int = Field(ge=0)
    target_revision: int = Field(ge=1)
    current_owner: ManagementOwner
    target_owner: Literal[ManagementOwner.PRODUCT] = ManagementOwner.PRODUCT
    lifecycle_owner: Literal[LifecycleOwner.PRODUCT] = LifecycleOwner.PRODUCT
    target_path: Literal["state/config/cc-connect.managed.toml"]
    expected_changes: list[str]
    ports: list[int] = Field(min_length=1, max_length=1)
    directories: list[str]
    secret_refs: list[SecretReference]
    risk: Literal["medium"] = "medium"
    rollback_plan: list[str]
    rollback_to_revision: int | None = None
    user_confirmation_required: Literal[True] = True
    created_at: datetime
    expires_at: datetime


class ConfigurationConfirmationRequest(StrictModel):
    plan_id: str
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    current_revision: int = Field(ge=0)
    target_revision: int = Field(ge=1)
    confirmation: Literal[True]


class ConfigurationState(StrictModel):
    component_id: Literal["cc-connect"] = "cc-connect"
    status: Literal["missing", "valid", "drifted", "invalid", "pending_repair"]
    revision: int = Field(ge=0)
    digest: str | None = None
    relative_path: Literal["state/config/cc-connect.managed.toml"]
    management_owner: ManagementOwner
    lifecycle_owner: LifecycleOwner
    configuration: ManagedConfiguration | None = None
    secret_status: dict[str, SecretStatus] = Field(default_factory=dict)
    diagnostic_code: str | None = None

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NativeTelegramPlatform(StrictModel):
    credential_reference_id: str
    environment_variable: str = Field(pattern=r"^AIAD_[A-Z0-9_]+$")
    allow_from: str = Field(min_length=1, max_length=512)
    group_reply_all: Literal[False] = False
    share_session_in_channel: Literal[False] = False
    progress_style: Literal["compact"] = "compact"


class NativeProject(StrictModel):
    project_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    display_name: str = Field(min_length=1, max_length=128)
    slot: Literal["claude", "codex"]
    agent_type: Literal["claudecode", "codex"]
    workspace_root: str = Field(min_length=1, max_length=1024)
    admin_from: str = Field(min_length=1, max_length=512)
    operator_user_id: int = Field(gt=0)
    group_chat_id: int
    binding_revision: int = Field(ge=1)
    telegram: NativeTelegramPlatform

    @model_validator(mode="after")
    def slot_matches_agent(self) -> NativeProject:
        expected = "claudecode" if self.slot == "claude" else "codex"
        if self.agent_type != expected:
            raise ValueError("slot and locked cc-connect agent type do not match")
        return self


class NativeRuntimeConfig(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    renderer_version: Literal["cc-connect-fc315d2-native-v1"] = "cc-connect-fc315d2-native-v1"
    source_commit: Literal["fc315d213b49d62e9d90ea4a510189d4115e636f"] = (
        "fc315d213b49d62e9d90ea4a510189d4115e636f"
    )
    data_dir: str = Field(min_length=1, max_length=1024)
    log_dir: str = Field(min_length=1, max_length=1024)
    management_port: int = Field(ge=59000, le=59999)
    management_credential_reference_id: str
    management_environment_variable: Literal["AIAD_CC_CONNECT_MANAGEMENT_TOKEN"] = (
        "AIAD_CC_CONNECT_MANAGEMENT_TOKEN"
    )
    projects: list[NativeProject] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def unique_projects(self) -> NativeRuntimeConfig:
        if len({item.project_id for item in self.projects}) != len(self.projects):
            raise ValueError("project identifiers must be unique")
        if len({item.slot for item in self.projects}) != len(self.projects):
            raise ValueError("bot slots must be unique")
        return self


class ManagedCcConnectState(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    product_instance_id: str
    artifact_id: str
    management_owner: Literal["product"] = "product"
    lifecycle_owner: Literal["product"] = "product"
    configuration_revision: int = Field(ge=1)
    runtime_config_revision: int = Field(ge=1)
    renderer_version: Literal["cc-connect-fc315d2-native-v1"] = "cc-connect-fc315d2-native-v1"
    source_commit: Literal["fc315d213b49d62e9d90ea4a510189d4115e636f"] = (
        "fc315d213b49d62e9d90ea4a510189d4115e636f"
    )
    binding_session_id: str
    binding_revision: int = Field(ge=1)
    operator_user_id: int = Field(gt=0)
    group_chat_id: int
    credential_references: list[str]
    bot_identities: dict[str, dict[str, str | int | bool]]
    runtime_config_relative_path: Literal["state/runtime-config/cc-connect.toml"] = (
        "state/runtime-config/cc-connect.toml"
    )
    native_group_chat_filter_status: Literal["unsupported"] = "unsupported"
    agent_authentication_status: Literal["unknown"] = "unknown"
    process_identity_reference: str | None = None
    health_evidence_reference: str | None = None
    backup_references: list[str] = Field(default_factory=list)
    audit_references: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class NativeRendererCapability(StrictModel):
    renderer_version: Literal["cc-connect-fc315d2-native-v1"]
    source_commit: Literal["fc315d213b49d62e9d90ea4a510189d4115e636f"]
    environment_placeholders_supported: Literal[True] = True
    project_types: list[Literal["claudecode", "codex"]]
    telegram_platform_supported: Literal[True] = True
    allow_from_supported: Literal[True] = True
    admin_from_supported: Literal[True] = True
    group_chat_filter_supported: Literal[False] = False
    management_api_bind_host: Literal["all_interfaces_upstream_limit"] = (
        "all_interfaces_upstream_limit"
    )
    management_api_bearer_required: Literal[True] = True
    config_must_remain_present: Literal[True] = True
    startup_argument: Literal["-config"] = "-config"


class NativeConfigurationPlanRequest(StrictModel):
    binding_session_id: str
    claude_workspace_root: str = Field(min_length=1, max_length=1024)
    codex_workspace_root: str = Field(min_length=1, max_length=1024)
    management_port: int = Field(default=59020, ge=59000, le=59999)
    expires_in_seconds: int = Field(default=900, ge=60, le=3600)
    rollback_to_revision: int | None = Field(default=None, ge=1)


class NativeConfigurationPlan(StrictModel):
    plan_id: str
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    context_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    current_revision: int = Field(ge=0)
    target_revision: int = Field(ge=1)
    artifact_id: str
    renderer_version: str
    managed_state_relative_path: Literal["state/managed/cc-connect-state.json"]
    runtime_config_relative_path: Literal["state/runtime-config/cc-connect.toml"]
    expected_changes: list[str]
    secret_environment_variables: list[str]
    rollback_to_revision: int | None = None
    created_at: datetime
    expires_at: datetime
    user_confirmation_required: Literal[True] = True


class NativeConfigurationConfirmation(StrictModel):
    plan_id: str
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    current_revision: int = Field(ge=0)
    target_revision: int = Field(ge=1)
    confirmation: Literal[True]


class NativeConfigurationState(StrictModel):
    status: Literal["missing", "valid", "drifted", "invalid", "pending_repair"]
    revision: int = Field(ge=0)
    runtime_config_digest: str | None = None
    managed_state_digest: str | None = None
    runtime_config: NativeRuntimeConfig | None = None
    managed_state: ManagedCcConnectState | None = None
    diagnostic_code: str | None = None

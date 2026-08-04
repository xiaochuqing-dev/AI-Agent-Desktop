from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InstallerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PatchDigest(InstallerModel):
    filename: str = Field(pattern=r"^[0-9]{3}-[A-Za-z0-9._-]+\.patch$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ArtifactManifest(InstallerModel):
    schema_version: str
    component_id: Literal["cc-connect"]
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    platform: Literal["windows"]
    architecture: Literal["amd64"]
    source_repo: str
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    upstream_version: str
    version: str
    patchset_version: str
    patch_files: list[PatchDigest] = Field(min_length=1)
    patch_sha256: list[str] = Field(min_length=1)
    go_version: str
    build_tags: list[str]
    ldflags: str
    source_date_epoch: int = Field(ge=0)
    build_timestamp_policy: str
    artifact_filename: Literal["cc-connect.exe"]
    artifact_size: int = Field(gt=0)
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    signature_status: Literal["unsigned"]
    created_at: datetime
    compatibility: dict[str, Any]
    minimum_os: str
    install_layout_version: str
    health_probe_version: str
    health_probe: dict[str, Any]

    @model_validator(mode="after")
    def validate_patch_digest_projection(self) -> ArtifactManifest:
        if self.patch_sha256 != [item.sha256 for item in self.patch_files]:
            raise ValueError("patch_sha256 must exactly match patch_files order")
        return self


class ArtifactSource(InstallerModel):
    source_ref: str = Field(min_length=1, max_length=128)
    kind: Literal["trusted_local_bundle", "https"]
    manifest_url: str | None = None
    artifact_url: str | None = None
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class InstallPlan(InstallerModel):
    plan_id: str
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    component_id: Literal["cc-connect"]
    artifact_id: str
    source: ArtifactSource
    source_commit: str
    patchset: str
    version: str
    architecture: Literal["amd64"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    install_root: str
    target_version_dir: str
    current_version: str | None
    current_owner: Literal["external", "product", "unmanaged", "conflict", "unknown"]
    required_disk_space: int = Field(gt=0)
    requires_admin: Literal[False] = False
    expected_changes: list[str]
    prerequisites: list[str]
    rollback_plan: list[str]
    risk: Literal["low", "medium", "high"]
    point_of_no_return: str
    user_confirmation_required: Literal[True] = True
    created_at: datetime
    expires_at: datetime


class InstallSnapshot(InstallerModel):
    snapshot_id: str
    operation_id: str
    component_id: Literal["cc-connect"]
    plan_id: str
    current_pointer: dict[str, Any] | None
    current_version: str | None
    install_directory_digest: str
    management_owner: Literal["external", "product", "unmanaged", "conflict", "unknown"]
    lifecycle_owner: Literal["external", "product", "unmanaged", "unknown"]
    discovery_state: str
    configuration_reference: str
    product_managed_process_running: bool
    disk_free_bytes: int
    target_directory_state: Literal["absent", "complete", "incomplete"]
    created_at: datetime


class ManagedVersion(InstallerModel):
    artifact_id: str
    version: str
    artifact_sha256: str
    artifact_size: int
    status: Literal["installed", "uninstalled", "pending_cleanup"]
    current: bool
    installed_at: datetime
    removed_at: datetime | None = None


class InstallPlanRequest(InstallerModel):
    source_ref: str = Field(min_length=1, max_length=128)
    expected_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    manifest_url: str | None = None
    artifact_url: str | None = None
    expires_in_seconds: int = Field(default=900, ge=60, le=3600)


class InstallConfirmationRequest(InstallerModel):
    version_policy: Literal["exact"] = "exact"
    requested_version: str
    source_ref: str
    expected_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    confirm: Literal[True]
    plan_id: str
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    confirmation: Literal[True]
    deadline_at: datetime | None = None


class UninstallRequest(InstallerModel):
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    confirm: Literal[True]


class RestoreRequest(InstallerModel):
    artifact_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    confirm: Literal[True]


class OperationAuditEvent(InstallerModel):
    event_id: int
    operation_id: str
    sequence: int
    event_type: str
    phase: str
    data: dict[str, Any]
    created_at: datetime

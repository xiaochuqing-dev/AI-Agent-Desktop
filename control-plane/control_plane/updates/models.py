from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UpdateChannel(StrEnum):
    LOCKED = "locked"
    EXACT = "exact"


class ComponentDescriptor(StrictModel):
    component_id: str
    display_name: str
    provider_id: str
    supports_multiple_installed_versions: bool
    configuration_schema_version: str | None = None


class InstalledVersion(StrictModel):
    component_id: str
    artifact_id: str
    version: str
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    current: bool


class AvailableVersion(StrictModel):
    component_id: str
    artifact_id: str
    version: str
    artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    channel: UpdateChannel
    source_kind: Literal["artifact_lock", "unsupported"]


class VersionPolicy(StrictModel):
    channel: Literal[UpdateChannel.EXACT, UpdateChannel.LOCKED]
    requested_version: str
    allow_prerelease: Literal[False] = False
    use_latest: Literal[False] = False


class CompatibilityRule(StrictModel):
    rule_id: str
    status: Literal["compatible", "incompatible", "unknown"]
    reason: str


class MigrationPlan(StrictModel):
    required: bool
    entrypoint: str
    from_schema_version: str | None
    to_schema_version: str | None
    status: Literal["not_required", "planned", "unsupported", "unknown"]


class UpdateAssessment(StrictModel):
    assessment_id: str
    component_id: str
    current_version: InstalledVersion | None
    target_version: AvailableVersion | None
    status: Literal["compatible", "already_current", "unsupported", "unknown"]
    compatibility: list[CompatibilityRule]
    migration: MigrationPlan
    rollback_version: InstalledVersion | None
    automatic_update_performed: Literal[False] = False
    upstream_patch_modified: Literal[False] = False


class ArtifactProvider(Protocol):
    provider_id: str

    def descriptor(self) -> ComponentDescriptor: ...

    def installed_versions(self) -> list[InstalledVersion]: ...

    def available_version(self, policy: VersionPolicy) -> AvailableVersion | None: ...

    def assess(self, policy: VersionPolicy) -> UpdateAssessment: ...


class UpdateSource(Protocol):
    source_id: str

    def resolve(self, component_id: str, policy: VersionPolicy) -> AvailableVersion | None: ...

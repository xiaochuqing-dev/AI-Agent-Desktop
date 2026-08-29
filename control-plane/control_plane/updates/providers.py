from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from ..installer.artifacts import InstallerError, load_artifact_lock
from ..installer.version_store import ManagedVersionStore
from ..persistence.models import ArtifactRecord, ComponentVersionRecord, UpdateAssessmentRecord
from ..persistence.session import Database
from .models import (
    AvailableVersion,
    CompatibilityRule,
    ComponentDescriptor,
    InstalledVersion,
    MigrationPlan,
    UpdateAssessment,
    UpdateChannel,
    VersionPolicy,
)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


class CcConnectArtifactProvider:
    provider_id = "cc-connect-locked-artifact"

    def __init__(self, database: Database, version_store: ManagedVersionStore) -> None:
        self.db = database
        self.version_store = version_store

    def descriptor(self) -> ComponentDescriptor:
        return ComponentDescriptor(
            component_id="cc-connect",
            display_name="cc-connect",
            provider_id=self.provider_id,
            supports_multiple_installed_versions=True,
            configuration_schema_version="1.0",
        )

    def installed_versions(self) -> list[InstalledVersion]:
        try:
            current_id = self.version_store.current().artifact_id
        except InstallerError:
            current_id = None
        with self.db.session() as session:
            records = list(
                session.query(ComponentVersionRecord)
                .filter(
                    ComponentVersionRecord.component_id == "cc-connect",
                    ComponentVersionRecord.status == "installed",
                )
                .order_by(ComponentVersionRecord.installed_at.desc())
            )
        return [
            InstalledVersion(
                component_id="cc-connect",
                artifact_id=record.artifact_id,
                version=record.version,
                artifact_sha256=record.artifact_sha256,
                current=record.artifact_id == current_id,
            )
            for record in records
        ]

    def available_version(self, policy: VersionPolicy) -> AvailableVersion | None:
        lock = load_artifact_lock()
        version = str(lock["version"])
        if policy.use_latest or policy.requested_version != version:
            return None
        artifact_id = str(lock["artifact_id"])
        with self.db.session() as session:
            artifact = session.get(ArtifactRecord, artifact_id)
        if artifact is None:
            return None
        return AvailableVersion(
            component_id="cc-connect",
            artifact_id=artifact_id,
            version=version,
            artifact_sha256=artifact.artifact_sha256,
            channel=UpdateChannel.LOCKED,
            source_kind="artifact_lock",
        )

    def assess(self, policy: VersionPolicy) -> UpdateAssessment:
        installed = self.installed_versions()
        current = next((item for item in installed if item.current), None)
        target = self.available_version(policy)
        if target is None:
            status: Literal["compatible", "already_current", "unsupported", "unknown"] = (
                "unsupported"
            )
            compatibility = [
                CompatibilityRule(
                    rule_id="exact-locked-version",
                    status="incompatible",
                    reason="Only an exact version present in the artifact lock can be assessed.",
                )
            ]
        elif current and current.artifact_id == target.artifact_id:
            status = "already_current"
            compatibility = [
                CompatibilityRule(
                    rule_id="locked-artifact-identity",
                    status="compatible",
                    reason="Installed current artifact exactly matches the lock.",
                )
            ]
        else:
            status = "compatible"
            compatibility = [
                CompatibilityRule(
                    rule_id="windows-amd64-lock",
                    status="compatible",
                    reason="Target comes from the verified Windows AMD64 artifact lock.",
                )
            ]
            if current is not None:
                compatibility.append(
                    CompatibilityRule(
                        rule_id="native-configuration-revision-refresh",
                        status="compatible",
                        reason=(
                            "After the stopped artifact switch, apply a new native configuration "
                            "revision before restarting the product-managed runtime."
                        ),
                    )
                )
        configuration_refresh_required = bool(
            current is not None and target is not None and current.artifact_id != target.artifact_id
        )
        assessment = UpdateAssessment(
            assessment_id=new_id("update"),
            component_id="cc-connect",
            current_version=current,
            target_version=target,
            status=status,
            compatibility=compatibility,
            migration=MigrationPlan(
                required=configuration_refresh_required,
                entrypoint=(
                    "cc_connect.native_configuration.create_plan"
                    if configuration_refresh_required
                    else "configuration.migrations.assess"
                ),
                from_schema_version="1.0" if current else None,
                to_schema_version="1.0" if target else None,
                status=(
                    "planned"
                    if configuration_refresh_required
                    else ("not_required" if target else "unknown")
                ),
            ),
            rollback_version=current,
        )
        with self.db.session() as session:
            session.add(
                UpdateAssessmentRecord(
                    assessment_id=assessment.assessment_id,
                    component_id="cc-connect",
                    current_version=current.version if current else None,
                    target_version=target.version if target else policy.requested_version,
                    status=assessment.status,
                    assessment_json=assessment.model_dump_json(),
                    created_at=datetime.now(UTC),
                )
            )
        return assessment


class HermesUpdateProvider:
    provider_id = "hermes-update-boundary"

    def descriptor(self) -> ComponentDescriptor:
        return ComponentDescriptor(
            component_id="hermes",
            display_name="Hermes",
            provider_id=self.provider_id,
            supports_multiple_installed_versions=False,
            configuration_schema_version=None,
        )

    def installed_versions(self) -> list[InstalledVersion]:
        return []

    def available_version(self, _policy: VersionPolicy) -> AvailableVersion | None:
        return None

    def assess(self, _policy: VersionPolicy) -> UpdateAssessment:
        return UpdateAssessment(
            assessment_id=new_id("update"),
            component_id="hermes",
            current_version=None,
            target_version=None,
            status="unsupported",
            compatibility=[
                CompatibilityRule(
                    rule_id="hermes-update-not-implemented",
                    status="unknown",
                    reason="This slice defines the provider boundary but does not install or update Hermes.",
                )
            ],
            migration=MigrationPlan(
                required=False,
                entrypoint="hermes.adapter.migrations.assess",
                from_schema_version=None,
                to_schema_version=None,
                status="unsupported",
            ),
            rollback_version=None,
        )

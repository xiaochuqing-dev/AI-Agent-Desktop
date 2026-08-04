from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import psutil
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from ..application.event_log import EventLog
from ..application.operation_store import OperationStore
from ..domain.models import Operation, OperationStatus, ResourceRef, UserFacingError
from ..infrastructure.config import Settings
from ..persistence.models import (
    ArtifactRecord,
    ComponentVersionRecord,
    DiagnosticRecord,
    IdempotencyRecord,
    InstallationLeaseRecord,
    InstallPlanRecord,
    InstallRecordRecord,
    InstallSnapshotRecord,
    OperationEventRecord,
    PendingCleanupRecord,
)
from ..persistence.session import Database
from ..security.redaction import redact_value
from .artifacts import (
    MANIFEST_FILENAME,
    ArtifactDownloader,
    InstallerError,
    copy_locked_bundle,
    load_manifest,
    run_isolated_version_probe,
    sha256_bytes,
    validate_download_url,
    validate_manifest_lock,
    verify_artifact_file,
)
from .models import (
    ArtifactManifest,
    ArtifactSource,
    InstallConfirmationRequest,
    InstallPlan,
    InstallPlanRequest,
    InstallSnapshot,
    ManagedVersion,
    OperationAuditEvent,
    RestoreRequest,
    UninstallRequest,
)
from .paths import ComponentLayout, atomic_write_json

COMPONENT_ID: Literal["cc-connect"] = "cc-connect"
ManagementOwner = Literal["external", "product", "unmanaged", "conflict", "unknown"]
TERMINAL_STATUSES = {
    OperationStatus.SUCCEEDED,
    OperationStatus.FAILED,
    OperationStatus.CANCELED,
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return "sha256:" + sha256_bytes(encoded)


class InstallerCancelled(InstallerError):
    def __init__(self) -> None:
        super().__init__(
            "OPERATION_CANCELED",
            "Installation was canceled at a safe checkpoint.",
            recovery_actions=["create_new_install_plan_if_needed"],
        )


class CcConnectInstaller:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        events: EventLog,
        *,
        fault_injector: Callable[[str, str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.db = database
        self.events = events
        self.layout = ComponentLayout(settings.components_dir)
        self.downloader = ArtifactDownloader(
            allowed_hosts=settings.allowed_download_hosts,
            timeout_seconds=settings.download_timeout_seconds,
            retries=settings.download_retries,
        )
        self.fault_injector = fault_injector

    def create_plan(self, request: InstallPlanRequest) -> InstallPlan:
        manifest, _raw_manifest, source = self._resolve_plan_source(request)
        if manifest.artifact_size > self.settings.artifact_max_bytes:
            raise InstallerError(
                "ARTIFACT_SIZE_LIMIT_EXCEEDED",
                "Locked artifact exceeds the configured installation size limit.",
                recovery_actions=["review_artifact_limit", "obtain_locked_artifact"],
            )
        expected = f"sha256:{manifest.artifact_sha256}"
        if request.expected_digest != expected:
            raise InstallerError(
                "EXPECTED_DIGEST_MISMATCH",
                "Requested digest does not match the locked artifact manifest.",
                recovery_actions=["refresh_install_plan"],
            )
        current = self.layout.read_current()
        current_version = str(current.get("version")) if current else None
        plan = InstallPlan(
            plan_id=new_id("plan"),
            plan_digest="sha256:" + "0" * 64,
            component_id=COMPONENT_ID,
            artifact_id=manifest.artifact_id,
            source=source,
            source_commit=manifest.source_commit,
            patchset=manifest.patchset_version,
            version=manifest.version,
            architecture="amd64",
            sha256=manifest.artifact_sha256,
            install_root="product-data://components/cc-connect",
            target_version_dir=f"versions/{manifest.artifact_id}",
            current_version=current_version,
            current_owner=self._management_owner(current),
            required_disk_space=manifest.artifact_size * 3 + 16 * 1024 * 1024,
            requires_admin=False,
            expected_changes=[
                f"create or verify versions/{manifest.artifact_id}",
                "write an install record in the product-owned directory",
                "atomically update product current.json after validation",
            ],
            prerequisites=[
                "ordinary current-user write access to product data",
                "locked artifact and manifest available",
                "sufficient free disk space",
            ],
            rollback_plan=[
                "restore the previous product current.json",
                "revalidate the previous product-managed artifact",
                "leave external lifecycle ownership unchanged",
            ],
            risk="medium",
            point_of_no_return="atomic_current_pointer_replace",
            user_confirmation_required=True,
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(seconds=request.expires_in_seconds),
        )
        plan = plan.model_copy(
            update={
                "plan_digest": canonical_digest(
                    plan.model_dump(mode="json", exclude={"plan_digest"})
                )
            }
        )
        with self.db.session() as session:
            session.merge(
                ArtifactRecord(
                    artifact_id=manifest.artifact_id,
                    component_id=COMPONENT_ID,
                    source_ref=request.source_ref,
                    manifest_json=manifest.model_dump_json(),
                    manifest_sha256=source.manifest_sha256,
                    artifact_sha256=manifest.artifact_sha256,
                    artifact_size=manifest.artifact_size,
                    created_at=utcnow(),
                )
            )
            session.add(
                InstallPlanRecord(
                    plan_id=plan.plan_id,
                    component_id=COMPONENT_ID,
                    artifact_id=manifest.artifact_id,
                    plan_digest=plan.plan_digest,
                    plan_json=plan.model_dump_json(),
                    source_json=source.model_dump_json(),
                    status="waiting_for_confirmation",
                    created_at=plan.created_at,
                    expires_at=plan.expires_at,
                    confirmed_at=None,
                )
            )
        return plan

    def get_plan(self, plan_id: str) -> InstallPlan | None:
        with self.db.session() as session:
            record = session.get(InstallPlanRecord, plan_id)
            return InstallPlan.model_validate_json(record.plan_json) if record else None

    def confirm_install(
        self,
        request: InstallConfirmationRequest,
        *,
        idempotency_key: str,
        body: bytes,
    ) -> tuple[Operation, bool]:
        try:
            with self.db.session() as session:
                store = OperationStore(session)
                existing = session.get(IdempotencyRecord, idempotency_key)
                if existing is not None:
                    return store.create(
                        kind="cc_connect_install",
                        target_ref=ResourceRef(kind="component", id=COMPONENT_ID),
                        idempotency_key=idempotency_key,
                        method="POST",
                        resource="/api/v1/components/cc-connect:install",
                        body=body,
                    )
                plan_record = session.get(InstallPlanRecord, request.plan_id)
                if plan_record is None:
                    raise InstallerError(
                        "INSTALL_PLAN_NOT_FOUND",
                        "Install plan was not found.",
                        recovery_actions=["create_install_plan"],
                    )
                plan = InstallPlan.model_validate_json(plan_record.plan_json)
                self._validate_confirmation(plan, request)
                if plan_record.status != "waiting_for_confirmation":
                    raise InstallerError(
                        "INSTALL_PLAN_ALREADY_USED",
                        "Install plan was already confirmed and cannot create another operation.",
                        recovery_actions=["create_install_plan"],
                    )
                if session.get(InstallationLeaseRecord, COMPONENT_ID) is not None:
                    raise InstallerError(
                        "INSTALLATION_ALREADY_RUNNING",
                        "Another cc-connect installation operation owns the component lease.",
                        retryable=True,
                        recovery_actions=["wait_for_active_operation"],
                    )
                operation, reused = store.create(
                    kind="cc_connect_install",
                    target_ref=ResourceRef(kind="component", id=COMPONENT_ID),
                    idempotency_key=idempotency_key,
                    method="POST",
                    resource="/api/v1/components/cc-connect:install",
                    body=body,
                )
                session.add(
                    InstallationLeaseRecord(
                        component_id=COMPONENT_ID,
                        operation_id=operation.operation_id,
                        acquired_at=utcnow(),
                    )
                )
                plan_record.status = "confirmed"
                plan_record.confirmed_at = utcnow()
                return operation, reused
        except IntegrityError:
            raise InstallerError(
                "INSTALLATION_ALREADY_RUNNING",
                "Another cc-connect installation operation acquired the component lease.",
                retryable=True,
                recovery_actions=["wait_for_active_operation"],
            ) from None

    def create_uninstall_operation(
        self, request: UninstallRequest, *, idempotency_key: str, body: bytes
    ) -> tuple[Operation, bool]:
        return self._create_maintenance_operation(
            kind="cc_connect_uninstall",
            idempotency_key=idempotency_key,
            body=body,
            resource="/api/v1/components/cc-connect:uninstall",
        )

    def create_restore_operation(
        self, request: RestoreRequest, *, idempotency_key: str, body: bytes
    ) -> tuple[Operation, bool]:
        return self._create_maintenance_operation(
            kind="cc_connect_restore",
            idempotency_key=idempotency_key,
            body=body,
            resource="/api/v1/components/cc-connect:restore",
        )

    def _create_maintenance_operation(
        self, *, kind: str, idempotency_key: str, body: bytes, resource: str
    ) -> tuple[Operation, bool]:
        try:
            with self.db.session() as session:
                store = OperationStore(session)
                existing = session.get(IdempotencyRecord, idempotency_key)
                if existing is not None:
                    return store.create(
                        kind=kind,
                        target_ref=ResourceRef(kind="component", id=COMPONENT_ID),
                        idempotency_key=idempotency_key,
                        method="POST",
                        resource=resource,
                        body=body,
                    )
                if session.get(InstallationLeaseRecord, COMPONENT_ID) is not None:
                    raise InstallerError(
                        "INSTALLATION_ALREADY_RUNNING",
                        "Another cc-connect maintenance operation is active.",
                        retryable=True,
                        recovery_actions=["wait_for_active_operation"],
                    )
                operation, reused = store.create(
                    kind=kind,
                    target_ref=ResourceRef(kind="component", id=COMPONENT_ID),
                    idempotency_key=idempotency_key,
                    method="POST",
                    resource=resource,
                    body=body,
                )
                session.add(
                    InstallationLeaseRecord(
                        component_id=COMPONENT_ID,
                        operation_id=operation.operation_id,
                        acquired_at=utcnow(),
                    )
                )
                return operation, reused
        except IntegrityError:
            raise InstallerError(
                "INSTALLATION_ALREADY_RUNNING",
                "Another cc-connect maintenance operation acquired the component lease.",
                retryable=True,
                recovery_actions=["wait_for_active_operation"],
            ) from None

    def execute_install(self, operation_id: str, plan_id: str, correlation_id: str) -> None:
        stage_dir = self.layout.staging_dir(operation_id)
        snapshot: InstallSnapshot | None = None
        manifest: ArtifactManifest | None = None
        target_created = False
        current_activated = False
        install_recorded = False
        try:
            self._phase(
                operation_id, "preflight", "Checking product-owned installation prerequisites"
            )
            self._check_cancellation(operation_id)
            self.layout.ensure()
            if stage_dir.exists():
                raise InstallerError(
                    "STAGING_DIRECTORY_CONFLICT",
                    "Operation staging directory already exists before execution.",
                    recovery_actions=["inspect_product_state", "retry_after_cleanup"],
                )
            stage_dir.mkdir(parents=True)
            plan, manifest, source = self._load_execution_inputs(plan_id)
            self._check_cancellation(operation_id)
            disk_free = shutil.disk_usage(self.layout.root).free
            if disk_free < plan.required_disk_space:
                raise InstallerError(
                    "DISK_SPACE_INSUFFICIENT",
                    "Insufficient free space for staging, verification, and rollback.",
                    retryable=True,
                    recovery_actions=["free_disk_space", "retry_installation"],
                    technical_details={
                        "required_bytes": plan.required_disk_space,
                        "available_bytes": disk_free,
                    },
                )
            self._phase(operation_id, "snapshotting", "Recording the pre-install product state")
            snapshot = self._capture_snapshot(operation_id, plan, disk_free)
            self._persist_snapshot(snapshot)
            self._check_cancellation(operation_id)

            acquired_dir = self._stage_child(operation_id, "acquired")
            self._phase(operation_id, "acquiring", "Acquiring the locked artifact into staging")
            acquired_manifest, raw_manifest = self._acquire(
                source, acquired_dir, operation_id=operation_id
            )
            if acquired_manifest.model_dump() != manifest.model_dump():
                raise InstallerError(
                    "MANIFEST_CHANGED_AFTER_CONFIRMATION",
                    "Artifact manifest changed after plan confirmation.",
                    recovery_actions=["create_new_install_plan"],
                )
            self._check_cancellation(operation_id)

            artifact_path = acquired_dir / manifest.artifact_filename
            self._phase(
                operation_id, "verifying", "Verifying size, SHA256, manifest, and PE architecture"
            )
            verify_artifact_file(
                artifact_path,
                manifest,
                cancel_check=lambda: self._check_cancellation(operation_id),
            )
            self._check_cancellation(operation_id)

            staged_version = self._stage_child(operation_id, "version")
            self._phase(
                operation_id, "installing_to_staging", "Creating an immutable staged version"
            )
            self._write_staged_version(
                staged_version, artifact_path, manifest, raw_manifest, operation_id, snapshot
            )
            self._check_cancellation(operation_id)

            self._phase(operation_id, "validating", "Running an isolated no-network version probe")
            staged_artifact = staged_version / manifest.artifact_filename
            verify_artifact_file(
                staged_artifact,
                manifest,
                cancel_check=lambda: self._check_cancellation(operation_id),
            )
            run_isolated_version_probe(
                staged_artifact,
                manifest,
                work_parent=self._stage_child(operation_id, "probe"),
                cancel_check=lambda: self._check_cancellation(operation_id),
            )
            self._check_cancellation(operation_id)

            self._revalidate_plan(plan_id, plan.plan_digest)
            current_before_activation = self.layout.read_current()
            if current_before_activation != snapshot.current_pointer:
                raise InstallerError(
                    "CURRENT_POINTER_CHANGED",
                    "Product current pointer changed after planning; activation was blocked.",
                    retryable=True,
                    recovery_actions=["create_new_install_plan"],
                )
            if (
                current_before_activation
                and current_before_activation.get("artifact_id") == manifest.artifact_id
                and current_before_activation.get("artifact_sha256") == manifest.artifact_sha256
            ):
                self._validate_managed_version_target(
                    manifest.artifact_id,
                    cancel_check=lambda: self._check_cancellation(operation_id),
                )
                pending_cleanup = not self._remove_path_or_defer(
                    stage_dir, operation_id, "STAGING_CLEANUP"
                )
                self._set_plan_status(plan_id, "completed")
                self._complete(
                    operation_id,
                    phase="completed",
                    result={
                        "component_id": COMPONENT_ID,
                        "artifact_id": manifest.artifact_id,
                        "version": manifest.version,
                        "artifact_sha256": manifest.artifact_sha256,
                        "already_installed": True,
                        "pending_cleanup": pending_cleanup,
                    },
                )
                return
            target = self.layout.version_dir(manifest.artifact_id)
            self._phase(operation_id, "activating", "Preparing the versioned product activation")
            if target.exists():
                existing_manifest = self._validate_managed_version_target(
                    manifest.artifact_id,
                    cancel_check=lambda: self._check_cancellation(operation_id),
                )[1]
                if existing_manifest.artifact_sha256 != manifest.artifact_sha256:
                    raise InstallerError(
                        "INSTALLED_VERSION_CONFLICT",
                        "Existing version directory has a different digest.",
                        recovery_actions=["inspect_product_version_directory"],
                    )
            else:
                os.replace(staged_version, target)
                target_created = True

            installed_manifest, _ = load_manifest(target / MANIFEST_FILENAME)
            verify_artifact_file(
                target / installed_manifest.artifact_filename,
                installed_manifest,
                cancel_check=lambda: self._check_cancellation(operation_id),
            )
            if installed_manifest.model_dump() != manifest.model_dump():
                raise InstallerError(
                    "INSTALLED_VERSION_CONFLICT",
                    "Installed version directory does not match the confirmed artifact.",
                    recovery_actions=["inspect_product_version_directory"],
                )
            if self.layout.read_current() != snapshot.current_pointer:
                raise InstallerError(
                    "CURRENT_POINTER_CHANGED",
                    "Product current pointer changed before atomic activation.",
                    retryable=True,
                    recovery_actions=["create_new_install_plan"],
                )

            self._phase(
                operation_id,
                "activating",
                "Atomically switching the product current pointer",
                point_of_no_return=True,
            )
            current_payload = {
                "schema_version": "1.0",
                "artifact_id": manifest.artifact_id,
                "version": manifest.version,
                "artifact_sha256": manifest.artifact_sha256,
                "previous_artifact_id": (
                    snapshot.current_pointer.get("artifact_id")
                    if snapshot.current_pointer
                    else None
                ),
                "operation_id": operation_id,
                "activated_at": utcnow().isoformat(),
                "revision": new_id("current"),
            }
            self.layout.write_current(current_payload)
            current_activated = True
            self._record_install_success(operation_id, manifest, snapshot)
            install_recorded = True
            self._set_plan_status(plan_id, "completed")
            pending_cleanup = not self._remove_path_or_defer(
                stage_dir, operation_id, "STAGING_CLEANUP"
            )
            self._complete(
                operation_id,
                phase="completed",
                result={
                    "component_id": COMPONENT_ID,
                    "artifact_id": manifest.artifact_id,
                    "version": manifest.version,
                    "artifact_sha256": manifest.artifact_sha256,
                    "install_path": f"versions/{manifest.artifact_id}",
                    "management_owner": snapshot.management_owner,
                    "lifecycle_takeover": False,
                    "health_probe": "version_only",
                    "deep_health": "unsupported",
                    "pending_cleanup": pending_cleanup,
                },
            )
        except InstallerCancelled as exc:
            if (
                target_created
                and manifest is not None
                and not self._is_current_artifact(manifest.artifact_id)
            ):
                self._remove_path_or_defer(
                    self.layout.version_dir(manifest.artifact_id),
                    operation_id,
                    "CANCELED_VERSION_CLEANUP",
                )
            self._remove_path_or_defer(stage_dir, operation_id, "CANCELED_STAGING_CLEANUP")
            self._set_plan_status(plan_id, "canceled")
            self._cancel(operation_id, exc)
        except InstallerError as exc:
            self._handle_install_failure(
                operation_id,
                plan_id,
                stage_dir,
                snapshot,
                manifest,
                target_created,
                current_activated,
                install_recorded,
                exc,
            )
        except Exception as exc:
            self._handle_install_failure(
                operation_id,
                plan_id,
                stage_dir,
                snapshot,
                manifest,
                target_created,
                current_activated,
                install_recorded,
                InstallerError(
                    "INSTALLATION_INTERNAL_ERROR",
                    "Installation stopped because of an unexpected internal error.",
                    retryable=True,
                    recovery_actions=["inspect_diagnostic", "retry_after_review"],
                    technical_details={"error": type(exc).__name__},
                ),
            )
        finally:
            self._release_lease(operation_id)

    def _handle_install_failure(
        self,
        operation_id: str,
        plan_id: str,
        stage_dir: Path,
        snapshot: InstallSnapshot | None,
        manifest: ArtifactManifest | None,
        target_created: bool,
        current_activated: bool,
        install_recorded: bool,
        error: InstallerError,
    ) -> None:
        rollback_failed: InstallerError | None = None
        rolled_back = False
        owns_current = self._current_owned_by_operation(operation_id)
        if snapshot is not None and (current_activated or owns_current):
            try:
                self._phase(
                    operation_id,
                    "rolling_back",
                    "Restoring the previous product-managed current pointer",
                    invoke_fault=False,
                )
                self._restore_snapshot(snapshot)
                rolled_back = True
            except InstallerError as rollback_error:
                rollback_failed = rollback_error
            except Exception as rollback_error:
                rollback_failed = InstallerError(
                    "ROLLBACK_INTERNAL_ERROR",
                    "Automatic rollback stopped because of an internal error.",
                    technical_details={"error": type(rollback_error).__name__},
                )
        if install_recorded and manifest is not None:
            self._rollback_install_records(operation_id, manifest.artifact_id, target_created)
        if (
            target_created
            and manifest is not None
            and not self._is_current_artifact(manifest.artifact_id)
        ):
            self._remove_path_or_defer(
                self.layout.version_dir(manifest.artifact_id),
                operation_id,
                "FAILED_VERSION_CLEANUP",
            )
        self._remove_path_or_defer(stage_dir, operation_id, "FAILED_STAGING_CLEANUP")
        self._set_plan_status(plan_id, "failed")
        if rollback_failed is not None:
            self._fail(
                operation_id,
                InstallerError(
                    "ROLLBACK_FAILED",
                    "Installation failed and automatic rollback could not be completed.",
                    recovery_actions=[
                        "close_file_handles",
                        "restore_current_json_from_install_snapshot",
                        "verify_previous_artifact_sha256",
                    ],
                    technical_details={
                        "installation_error": error.code,
                        "rollback_error": rollback_failed.code,
                    },
                ),
                phase="rollback_failed",
            )
        else:
            self._fail(operation_id, error, phase="rolled_back" if rolled_back else "failed")

    def _rollback_install_records(
        self, operation_id: str, artifact_id: str, target_created: bool
    ) -> None:
        now = utcnow()
        with self.db.session() as session:
            records = list(
                session.scalars(
                    select(InstallRecordRecord).where(
                        InstallRecordRecord.operation_id == operation_id
                    )
                )
            )
            for record in records:
                record.status = "rolled_back"
                record.removed_at = now
            if target_created:
                version = session.get(ComponentVersionRecord, artifact_id)
                if version is not None:
                    session.delete(version)

    def _set_plan_status(self, plan_id: str, status: str) -> None:
        with self.db.session() as session:
            record = session.get(InstallPlanRecord, plan_id)
            if record is not None:
                record.status = status

    def execute_uninstall(
        self, operation_id: str, request: UninstallRequest, correlation_id: str
    ) -> None:
        try:
            self._phase(operation_id, "preflight", "Checking the requested product-managed version")
            current = self.layout.read_current()
            if current and current.get("artifact_id") == request.artifact_id:
                raise InstallerError(
                    "CURRENT_VERSION_IN_USE",
                    "Current product-managed version must be switched before uninstall.",
                    recovery_actions=["restore_another_version", "retry_uninstall"],
                )
            target, _ = self._validate_managed_version_target(
                request.artifact_id,
                cancel_check=lambda: self._check_cancellation(operation_id),
            )
            self._check_cancellation(operation_id)
            self._phase(
                operation_id,
                "uninstalling",
                "Removing only the selected non-current product-managed version",
                point_of_no_return=True,
            )
            if not self._remove_path_or_defer(target, operation_id, "VERSION_FILE_LOCKED"):
                self._mark_version_status(request.artifact_id, "pending_cleanup")
                raise InstallerError(
                    "PENDING_CLEANUP",
                    "Version is locked and was recorded for cleanup retry.",
                    retryable=True,
                    recovery_actions=["close_file_handles", "retry_pending_cleanup"],
                )
            self._mark_version_status(request.artifact_id, "uninstalled")
            self._complete(
                operation_id,
                phase="completed",
                result={"artifact_id": request.artifact_id, "status": "uninstalled"},
            )
        except InstallerCancelled as exc:
            self._cancel(operation_id, exc)
        except InstallerError as exc:
            self._fail(
                operation_id,
                exc,
                phase="pending_cleanup" if exc.code == "PENDING_CLEANUP" else "failed",
            )
        except Exception as exc:
            self._fail(
                operation_id,
                InstallerError(
                    "UNINSTALL_INTERNAL_ERROR",
                    "Uninstall stopped because of an unexpected internal error.",
                    retryable=True,
                    recovery_actions=["inspect_diagnostic", "retry_after_review"],
                    technical_details={"error": type(exc).__name__},
                ),
                phase="failed",
            )
        finally:
            self._release_lease(operation_id)

    def execute_restore(
        self, operation_id: str, request: RestoreRequest, correlation_id: str
    ) -> None:
        original: dict[str, Any] | None = None
        activated = False
        try:
            self._phase(operation_id, "preflight", "Resolving a previous product-managed version")
            original = self.layout.read_current()
            target_artifact = request.artifact_id or (
                str(original.get("previous_artifact_id"))
                if original and original.get("previous_artifact_id")
                else None
            )
            if not target_artifact:
                raise InstallerError(
                    "RESTORE_TARGET_NOT_AVAILABLE",
                    "No previous product-managed version is available.",
                    recovery_actions=["list_managed_versions"],
                )
            if original and original.get("artifact_id") == target_artifact:
                raise InstallerError(
                    "RESTORE_TARGET_ALREADY_CURRENT",
                    "Requested restore target is already current.",
                    recovery_actions=["select_previous_managed_version"],
                )
            target, manifest = self._validate_managed_version_target(
                target_artifact,
                cancel_check=lambda: self._check_cancellation(operation_id),
            )
            artifact = target / manifest.artifact_filename
            self._phase(operation_id, "validating", "Revalidating the restore target")
            verify_artifact_file(artifact, manifest)
            run_isolated_version_probe(
                artifact,
                manifest,
                work_parent=self._stage_child(operation_id, "probe"),
                cancel_check=lambda: self._check_cancellation(operation_id),
            )
            self._check_cancellation(operation_id)
            self._phase(
                operation_id,
                "activating",
                "Atomically restoring the selected product-managed version",
                point_of_no_return=True,
            )
            self.layout.write_current(
                {
                    "schema_version": "1.0",
                    "artifact_id": manifest.artifact_id,
                    "version": manifest.version,
                    "artifact_sha256": manifest.artifact_sha256,
                    "previous_artifact_id": original.get("artifact_id") if original else None,
                    "operation_id": operation_id,
                    "activated_at": utcnow().isoformat(),
                    "revision": new_id("current"),
                }
            )
            activated = True
            self._complete(
                operation_id,
                phase="completed",
                result={"artifact_id": manifest.artifact_id, "status": "restored"},
            )
        except InstallerCancelled as exc:
            self._cancel(operation_id, exc)
        except InstallerError as exc:
            if activated or self._current_owned_by_operation(operation_id):
                try:
                    self._restore_current_pointer(original)
                except InstallerError as restore_rollback_error:
                    self._fail(
                        operation_id,
                        InstallerError(
                            "ROLLBACK_FAILED",
                            "Restore failed and the original current pointer could not be recovered.",
                            recovery_actions=["restore_current_json_manually"],
                            technical_details={"rollback_error": restore_rollback_error.code},
                        ),
                        phase="rollback_failed",
                    )
                    return
            self._fail(operation_id, exc, phase="rolled_back" if activated else "failed")
        except Exception as exc:
            rollback_failure_code: str | None = None
            if activated or self._current_owned_by_operation(operation_id):
                try:
                    self._restore_current_pointer(original)
                except InstallerError as unexpected_rollback_error:
                    rollback_failure_code = unexpected_rollback_error.code
            if rollback_failure_code is not None:
                failure = InstallerError(
                    "ROLLBACK_FAILED",
                    "Restore failed and the original pointer could not be recovered.",
                    recovery_actions=["restore_current_json_manually"],
                    technical_details={"rollback_error": rollback_failure_code},
                )
                phase = "rollback_failed"
            else:
                failure = InstallerError(
                    "RESTORE_INTERNAL_ERROR",
                    "Restore stopped because of an unexpected internal error.",
                    retryable=True,
                    recovery_actions=["inspect_diagnostic", "retry_after_review"],
                    technical_details={"error": type(exc).__name__},
                )
                phase = "rolled_back" if activated else "failed"
            self._fail(operation_id, failure, phase=phase)
        finally:
            self._remove_path_or_defer(
                self.layout.staging_dir(operation_id), operation_id, "RESTORE_STAGING_CLEANUP"
            )
            self._release_lease(operation_id)

    def list_managed_versions(self) -> list[ManagedVersion]:
        current = self.layout.read_current()
        current_id = current.get("artifact_id") if current else None
        with self.db.session() as session:
            records = list(
                session.scalars(
                    select(ComponentVersionRecord)
                    .where(ComponentVersionRecord.component_id == COMPONENT_ID)
                    .order_by(ComponentVersionRecord.installed_at.desc())
                )
            )
            return [
                ManagedVersion(
                    artifact_id=item.artifact_id,
                    version=item.version,
                    artifact_sha256=item.artifact_sha256,
                    artifact_size=item.artifact_size,
                    status=cast(
                        Literal["installed", "uninstalled", "pending_cleanup"], item.status
                    ),
                    current=item.artifact_id == current_id,
                    installed_at=item.installed_at,
                    removed_at=item.removed_at,
                )
                for item in records
            ]

    def list_audit_events(self, operation_id: str) -> list[OperationAuditEvent]:
        with self.db.session() as session:
            records = list(
                session.scalars(
                    select(OperationEventRecord)
                    .where(OperationEventRecord.operation_id == operation_id)
                    .order_by(OperationEventRecord.sequence)
                )
            )
            return [
                OperationAuditEvent(
                    event_id=item.event_id,
                    operation_id=item.operation_id,
                    sequence=item.sequence,
                    event_type=item.event_type,
                    phase=item.phase,
                    data=json.loads(item.data_json),
                    created_at=item.created_at,
                )
                for item in records
            ]

    def audit_cancel_requested(self, operation_id: str, *, point_of_no_return: bool) -> None:
        with self.db.session() as session:
            self._record_event_in_session(
                session,
                operation_id,
                "com.aiagentdesktop.operation.cancel_requested.v1",
                "cancel_requested",
                {"point_of_no_return": point_of_no_return},
            )
        self.events.emit(
            type_="com.aiagentdesktop.operation.cancel_requested.v1",
            subject=f"operation:{operation_id}",
            data={"point_of_no_return": point_of_no_return},
            resource_ref=ResourceRef(kind="component", id=COMPONENT_ID),
            correlation_id="installer",
            operation_id=operation_id,
        )

    def retry_pending_cleanup(self) -> int:
        if not self.layout.root.exists():
            return 0
        current = self.layout.read_current()
        current_id = current.get("artifact_id") if current else None
        removed = 0
        with self.db.session() as session:
            records = list(session.scalars(select(PendingCleanupRecord)))
            for record in records:
                try:
                    target = self.layout.from_relative(record.relative_path)
                    if current_id and target == self.layout.version_dir(str(current_id)):
                        record.attempts += 1
                        record.updated_at = utcnow()
                        continue
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink(missing_ok=True)
                    parts = Path(record.relative_path).parts
                    if len(parts) == 2 and parts[0] == "versions":
                        version = session.get(ComponentVersionRecord, parts[1])
                        if version is not None and version.status == "pending_cleanup":
                            version.status = "uninstalled"
                            version.removed_at = utcnow()
                        install_records = list(
                            session.scalars(
                                select(InstallRecordRecord).where(
                                    InstallRecordRecord.artifact_id == parts[1],
                                    InstallRecordRecord.status == "pending_cleanup",
                                )
                            )
                        )
                        for install_record in install_records:
                            install_record.status = "uninstalled"
                            install_record.removed_at = utcnow()
                    session.delete(record)
                    removed += 1
                except (OSError, InstallerError):
                    record.attempts += 1
                    record.updated_at = utcnow()
        self._write_pending_cleanup_state()
        return removed

    def recover_interrupted_operations(self) -> None:
        with self.db.session() as session:
            leases = list(session.scalars(select(InstallationLeaseRecord)))
        for lease in leases:
            with self.db.session() as session:
                store = OperationStore(session)
                operation = store.get(lease.operation_id)
                snapshot_record = session.scalar(
                    select(InstallSnapshotRecord).where(
                        InstallSnapshotRecord.operation_id == lease.operation_id
                    )
                )
            if operation is None:
                self._remove_path_or_defer(
                    self.layout.staging_dir(lease.operation_id),
                    lease.operation_id,
                    "ORPHAN_LEASE_STAGING_CLEANUP",
                )
                self._release_lease(lease.operation_id)
                continue
            if operation.status not in TERMINAL_STATUSES:
                continue
            if snapshot_record is not None and operation.status != OperationStatus.SUCCEEDED:
                snapshot = InstallSnapshot.model_validate_json(snapshot_record.snapshot_json)
                try:
                    if self._current_owned_by_operation(lease.operation_id):
                        self._restore_snapshot(snapshot)
                    if snapshot.target_directory_state == "absent":
                        artifact_id = self._plan_artifact_id(snapshot.plan_id)
                        target = self.layout.version_dir(artifact_id)
                        if (
                            target.exists()
                            and not self._is_current_artifact(artifact_id)
                            and self._target_owned_by_operation(target, lease.operation_id)
                        ):
                            self._remove_path_or_defer(
                                target,
                                lease.operation_id,
                                "RESTART_RECOVERY_VERSION_CLEANUP",
                            )
                        self._rollback_install_records(
                            lease.operation_id, artifact_id, target_created=True
                        )
                except InstallerError as exc:
                    self._fail(
                        lease.operation_id,
                        InstallerError(
                            "ROLLBACK_FAILED",
                            "Restart recovery could not restore the pre-install state.",
                            recovery_actions=[
                                "restore_current_json_from_install_snapshot",
                                "inspect_product_state",
                            ],
                            technical_details={"rollback_error": exc.code},
                        ),
                        phase="rollback_failed",
                    )
            self._remove_path_or_defer(
                self.layout.staging_dir(lease.operation_id),
                lease.operation_id,
                "RESTART_RECOVERY_STAGING_CLEANUP",
            )
            self._release_lease(lease.operation_id)
        self.retry_pending_cleanup()

    def _plan_artifact_id(self, plan_id: str) -> str:
        with self.db.session() as session:
            record = session.get(InstallPlanRecord, plan_id)
            if record is None:
                raise InstallerError("INSTALL_PLAN_NOT_FOUND", "Install plan is missing.")
            return record.artifact_id

    def _resolve_plan_source(
        self, request: InstallPlanRequest
    ) -> tuple[ArtifactManifest, bytes, ArtifactSource]:
        if request.manifest_url or request.artifact_url:
            if not request.manifest_url or not request.artifact_url:
                raise InstallerError(
                    "ARTIFACT_SOURCE_INCOMPLETE",
                    "HTTPS source requires both manifest and artifact URLs.",
                    recovery_actions=["use_locked_source"],
                )
            validate_download_url(request.manifest_url, self.settings.allowed_download_hosts)
            validate_download_url(request.artifact_url, self.settings.allowed_download_hosts)
            with tempfile.TemporaryDirectory(prefix="cc-connect-plan-") as temp_name:
                path = Path(temp_name) / MANIFEST_FILENAME
                self.downloader.download(request.manifest_url, path, max_bytes=1024 * 1024)
                manifest, raw = load_manifest(path)
            source = ArtifactSource(
                source_ref=request.source_ref,
                kind="https",
                manifest_url=request.manifest_url,
                artifact_url=request.artifact_url,
                manifest_sha256=sha256_bytes(raw),
            )
            return manifest, raw, source
        if request.source_ref != "trusted-local-bundle" or not self.settings.trusted_artifact_dir:
            raise InstallerError(
                "TRUSTED_ARTIFACT_SOURCE_UNAVAILABLE",
                "Trusted local artifact bundle is not configured.",
                recovery_actions=["configure_ci_artifact_bundle"],
            )
        source_dir = self._trusted_source_dir()
        manifest, raw = load_manifest(source_dir / MANIFEST_FILENAME)
        verify_artifact_file(source_dir / manifest.artifact_filename, manifest)
        source = ArtifactSource(
            source_ref=request.source_ref,
            kind="trusted_local_bundle",
            manifest_sha256=sha256_bytes(raw),
        )
        return manifest, raw, source

    def _validate_confirmation(
        self, plan: InstallPlan, request: InstallConfirmationRequest
    ) -> None:
        if utcnow() >= plan.expires_at:
            raise InstallerError(
                "INSTALL_PLAN_EXPIRED",
                "Install plan expired before confirmation.",
                recovery_actions=["create_install_plan"],
            )
        checks = (
            request.plan_digest == plan.plan_digest,
            request.source_ref == plan.source.source_ref,
            request.expected_digest == f"sha256:{plan.sha256}",
            request.requested_version == plan.version,
        )
        if not all(checks):
            raise InstallerError(
                "INSTALL_CONFIRMATION_MISMATCH",
                "Confirmation does not match the immutable install plan.",
                recovery_actions=["review_and_confirm_current_plan"],
            )

    def _load_execution_inputs(
        self, plan_id: str
    ) -> tuple[InstallPlan, ArtifactManifest, ArtifactSource]:
        with self.db.session() as session:
            plan_record = session.get(InstallPlanRecord, plan_id)
            if plan_record is None or plan_record.status != "confirmed":
                raise InstallerError(
                    "INSTALL_PLAN_NOT_CONFIRMED",
                    "Install plan is missing or not confirmed.",
                    recovery_actions=["confirm_install_plan"],
                )
            artifact_record = session.get(ArtifactRecord, plan_record.artifact_id)
            if artifact_record is None:
                raise InstallerError(
                    "ARTIFACT_RECORD_NOT_FOUND",
                    "Locked artifact record is missing.",
                    recovery_actions=["create_install_plan"],
                )
            plan = self._validate_stored_plan(plan_record)
            manifest = self._validate_stored_manifest(artifact_record.manifest_json)
            source = ArtifactSource.model_validate_json(plan_record.source_json)
            if (
                manifest.artifact_id != plan.artifact_id
                or manifest.artifact_sha256 != plan.sha256
                or artifact_record.artifact_sha256 != manifest.artifact_sha256
                or artifact_record.artifact_size != manifest.artifact_size
                or source != plan.source
            ):
                raise InstallerError(
                    "INSTALL_INPUT_RECORD_MISMATCH",
                    "Persisted artifact, source, and plan records no longer agree.",
                    recovery_actions=["create_install_plan"],
                )
            return plan, manifest, source

    def _validate_stored_plan(self, record: InstallPlanRecord) -> InstallPlan:
        plan = InstallPlan.model_validate_json(record.plan_json)
        computed = canonical_digest(plan.model_dump(mode="json", exclude={"plan_digest"}))
        if (
            computed != plan.plan_digest
            or record.plan_digest != plan.plan_digest
            or record.artifact_id != plan.artifact_id
        ):
            raise InstallerError(
                "INSTALL_PLAN_DIGEST_MISMATCH",
                "Persisted install plan no longer matches its immutable digest.",
                recovery_actions=["create_install_plan"],
            )
        return plan

    @staticmethod
    def _validate_stored_manifest(raw_manifest: str) -> ArtifactManifest:
        manifest = ArtifactManifest.model_validate_json(raw_manifest)
        validate_manifest_lock(manifest)
        return manifest

    def _revalidate_plan(self, plan_id: str, expected_digest: str) -> None:
        with self.db.session() as session:
            record = session.get(InstallPlanRecord, plan_id)
            if record is None or record.status != "confirmed":
                raise InstallerError(
                    "INSTALL_PLAN_NOT_CONFIRMED",
                    "Install plan is no longer confirmed.",
                    recovery_actions=["create_install_plan"],
                )
            plan = self._validate_stored_plan(record)
        if plan.plan_digest != expected_digest:
            raise InstallerError(
                "INSTALL_PLAN_CHANGED",
                "Install plan changed after confirmation.",
                recovery_actions=["create_install_plan"],
            )

    def _acquire(
        self, source: ArtifactSource, destination: Path, *, operation_id: str
    ) -> tuple[ArtifactManifest, bytes]:
        if source.kind == "trusted_local_bundle":
            if not self.settings.trusted_artifact_dir:
                raise InstallerError(
                    "TRUSTED_ARTIFACT_SOURCE_UNAVAILABLE",
                    "Trusted artifact bundle is no longer configured.",
                    recovery_actions=["configure_ci_artifact_bundle"],
                )
            manifest, raw = copy_locked_bundle(
                self._trusted_source_dir(),
                destination,
                cancel_check=lambda: self._check_cancellation(operation_id),
            )
        else:
            assert source.manifest_url and source.artifact_url
            manifest_path = destination / MANIFEST_FILENAME
            self.downloader.download(
                source.manifest_url,
                manifest_path,
                max_bytes=1024 * 1024,
                cancel_check=lambda: self._check_cancellation(operation_id),
            )
            manifest, raw = load_manifest(manifest_path)
            self.downloader.download(
                source.artifact_url,
                destination / manifest.artifact_filename,
                max_bytes=self.settings.artifact_max_bytes,
                cancel_check=lambda: self._check_cancellation(operation_id),
            )
            verify_artifact_file(
                destination / manifest.artifact_filename,
                manifest,
                cancel_check=lambda: self._check_cancellation(operation_id),
            )
        if sha256_bytes(raw) != source.manifest_sha256:
            raise InstallerError(
                "MANIFEST_CHANGED_AFTER_CONFIRMATION",
                "Manifest bytes changed after plan confirmation.",
                recovery_actions=["create_new_install_plan"],
            )
        return manifest, raw

    def _trusted_source_dir(self) -> Path:
        if not self.settings.trusted_artifact_dir:
            raise InstallerError(
                "TRUSTED_ARTIFACT_SOURCE_UNAVAILABLE",
                "Trusted local artifact bundle is not configured.",
                recovery_actions=["configure_ci_artifact_bundle"],
            )
        try:
            source = Path(self.settings.trusted_artifact_dir).resolve(strict=True)
        except OSError as exc:
            raise InstallerError(
                "TRUSTED_ARTIFACT_SOURCE_UNAVAILABLE",
                "Trusted local artifact bundle could not be resolved.",
                retryable=True,
                recovery_actions=["configure_ci_artifact_bundle"],
                technical_details={"error": type(exc).__name__},
            ) from None
        if not source.is_dir():
            raise InstallerError(
                "TRUSTED_ARTIFACT_SOURCE_UNAVAILABLE",
                "Trusted local artifact bundle is not a directory.",
                recovery_actions=["configure_ci_artifact_bundle"],
            )
        return source

    def _capture_snapshot(
        self, operation_id: str, plan: InstallPlan, disk_free: int
    ) -> InstallSnapshot:
        current = self.layout.read_current()
        target = self.layout.version_dir(plan.artifact_id)
        target_state: Literal["absent", "complete", "incomplete"]
        if not target.exists():
            target_state = "absent"
        elif (target / MANIFEST_FILENAME).is_file() and (target / "cc-connect.exe").is_file():
            target_state = "complete"
        else:
            target_state = "incomplete"
        return InstallSnapshot(
            snapshot_id=new_id("snapshot"),
            operation_id=operation_id,
            component_id=COMPONENT_ID,
            plan_id=plan.plan_id,
            current_pointer=current,
            current_version=str(current.get("version")) if current else None,
            install_directory_digest=self.layout.directory_digest(),
            management_owner=self._management_owner(current),
            lifecycle_owner=("external" if self._external_cc_connect_detected() else "unmanaged"),
            discovery_state="installed_external"
            if self._external_cc_connect_detected()
            else "unknown",
            configuration_reference=(
                "external_reference_present"
                if (Path.home() / ".cc-connect" / "config.toml").is_file()
                else "not_observed"
            ),
            product_managed_process_running=self._product_process_running(),
            disk_free_bytes=disk_free,
            target_directory_state=target_state,
            created_at=utcnow(),
        )

    def _persist_snapshot(self, snapshot: InstallSnapshot) -> None:
        backup = self.layout.backup_dir(snapshot.operation_id)
        backup.mkdir(parents=True, exist_ok=True)
        atomic_write_json(backup / "install-snapshot.json", snapshot.model_dump(mode="json"))
        with self.db.session() as session:
            session.add(
                InstallSnapshotRecord(
                    snapshot_id=snapshot.snapshot_id,
                    operation_id=snapshot.operation_id,
                    component_id=COMPONENT_ID,
                    snapshot_json=snapshot.model_dump_json(),
                    created_at=snapshot.created_at,
                )
            )

    def _write_staged_version(
        self,
        staged_version: Path,
        artifact_path: Path,
        manifest: ArtifactManifest,
        raw_manifest: bytes,
        operation_id: str,
        snapshot: InstallSnapshot,
    ) -> None:
        if staged_version.exists():
            shutil.rmtree(staged_version)
        staged_version.mkdir(parents=True)
        with (
            artifact_path.open("rb") as source,
            (staged_version / manifest.artifact_filename).open("wb") as destination,
        ):
            while True:
                self._check_cancellation(operation_id)
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        (staged_version / MANIFEST_FILENAME).write_bytes(raw_manifest)
        atomic_write_json(
            staged_version / "install-record.json",
            {
                "schema_version": "1.0",
                "operation_id": operation_id,
                "component_id": COMPONENT_ID,
                "artifact_id": manifest.artifact_id,
                "version": manifest.version,
                "artifact_sha256": manifest.artifact_sha256,
                "management_owner": snapshot.management_owner,
                "lifecycle_takeover": False,
                "installed_at": utcnow().isoformat(),
            },
        )

    def _record_install_success(
        self, operation_id: str, manifest: ArtifactManifest, snapshot: InstallSnapshot
    ) -> None:
        now = utcnow()
        relative = f"versions/{manifest.artifact_id}"
        with self.db.session() as session:
            session.merge(
                ComponentVersionRecord(
                    artifact_id=manifest.artifact_id,
                    component_id=COMPONENT_ID,
                    version=manifest.version,
                    relative_path=relative,
                    artifact_sha256=manifest.artifact_sha256,
                    artifact_size=manifest.artifact_size,
                    status="installed",
                    installed_at=now,
                    removed_at=None,
                )
            )
            session.add(
                InstallRecordRecord(
                    install_record_id=new_id("install"),
                    operation_id=operation_id,
                    component_id=COMPONENT_ID,
                    artifact_id=manifest.artifact_id,
                    version=manifest.version,
                    status="installed",
                    relative_path=relative,
                    artifact_sha256=manifest.artifact_sha256,
                    management_owner=snapshot.management_owner,
                    installed_at=now,
                    removed_at=None,
                )
            )

    def _mark_version_status(self, artifact_id: str, status: str) -> None:
        with self.db.session() as session:
            record = session.get(ComponentVersionRecord, artifact_id)
            if record:
                record.status = status
                if status == "uninstalled":
                    record.removed_at = utcnow()
            install_records = list(
                session.scalars(
                    select(InstallRecordRecord).where(
                        InstallRecordRecord.artifact_id == artifact_id,
                        InstallRecordRecord.status == "installed",
                    )
                )
            )
            for install_record in install_records:
                install_record.status = status
                if status == "uninstalled":
                    install_record.removed_at = utcnow()

    def _restore_snapshot(self, snapshot: InstallSnapshot) -> None:
        self._restore_current_pointer(snapshot.current_pointer)

    def _restore_current_pointer(self, pointer: dict[str, Any] | None) -> None:
        if pointer:
            artifact_id = str(pointer["artifact_id"])
            expected_digest = str(pointer["artifact_sha256"])
            self._validate_managed_version_target(
                artifact_id, expected_digest=expected_digest, allow_untracked_current=True
            )
        self.layout.restore_current(pointer)

    def _validate_managed_version_target(
        self,
        artifact_id: str,
        *,
        expected_digest: str | None = None,
        allow_untracked_current: bool = False,
        cancel_check: Callable[[], None] | None = None,
    ) -> tuple[Path, ArtifactManifest]:
        expected_relative = f"versions/{artifact_id}"
        with self.db.session() as session:
            record = session.get(ComponentVersionRecord, artifact_id)
            if record is None and not allow_untracked_current:
                raise InstallerError(
                    "MANAGED_VERSION_NOT_FOUND",
                    "Requested version is not registered as product-managed.",
                    recovery_actions=["list_managed_versions"],
                )
            if record is not None and (
                record.component_id != COMPONENT_ID
                or record.relative_path != expected_relative
                or record.status != "installed"
            ):
                raise InstallerError(
                    "MANAGED_VERSION_STATE_INVALID",
                    "Requested version is not an active product-managed installation.",
                    recovery_actions=["list_managed_versions", "inspect_product_state"],
                )
        target = self.layout.from_relative(expected_relative)
        manifest, _ = load_manifest(target / MANIFEST_FILENAME, enforce_lock=False)
        artifact = target / manifest.artifact_filename
        verify_artifact_file(artifact, manifest, cancel_check=cancel_check)
        if manifest.artifact_id != artifact_id:
            raise InstallerError(
                "MANAGED_VERSION_IDENTITY_MISMATCH",
                "Managed version directory does not match its manifest identity.",
                recovery_actions=["inspect_product_state"],
            )
        if expected_digest is not None and manifest.artifact_sha256 != expected_digest:
            raise InstallerError(
                "MANAGED_VERSION_DIGEST_MISMATCH",
                "Managed version does not match the recorded current digest.",
                recovery_actions=["inspect_product_state"],
            )
        if record is not None and (
            manifest.version != record.version
            or manifest.artifact_sha256 != record.artifact_sha256
            or manifest.artifact_size != record.artifact_size
        ):
            raise InstallerError(
                "MANAGED_VERSION_RECORD_MISMATCH",
                "Managed version files do not match the persistent install record.",
                recovery_actions=["inspect_product_state"],
            )
        install_record_path = target / "install-record.json"
        try:
            install_record = json.loads(install_record_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            raise InstallerError(
                "INSTALL_RECORD_INVALID",
                "Managed version install record is missing or invalid.",
                recovery_actions=["inspect_product_state"],
            ) from None
        if (
            install_record.get("component_id") != COMPONENT_ID
            or install_record.get("artifact_id") != artifact_id
            or install_record.get("artifact_sha256") != manifest.artifact_sha256
        ):
            raise InstallerError(
                "INSTALL_RECORD_MISMATCH",
                "Managed version install record does not match the artifact.",
                recovery_actions=["inspect_product_state"],
            )
        return target, manifest

    def _management_owner(self, current: dict[str, Any] | None) -> ManagementOwner:
        if self._external_cc_connect_detected():
            return "external"
        if current is None:
            return "unmanaged"
        with self.db.session() as session:
            record = session.get(ComponentVersionRecord, str(current.get("artifact_id", "")))
        return "product" if record is not None and record.status == "installed" else "unknown"

    def _external_cc_connect_detected(self) -> bool:
        candidate = shutil.which("cc-connect")
        if candidate and Path(candidate).is_file():
            try:
                if Path(candidate).resolve().is_relative_to(self.layout.root.resolve(strict=False)):
                    return False
            except OSError:
                pass
            return True
        appdata = os.environ.get("APPDATA")
        if appdata:
            legacy = (
                Path(appdata) / "npm" / "node_modules" / "cc-connect" / "bin" / "cc-connect.exe"
            )
            return legacy.is_file()
        return False

    def _product_process_running(self) -> bool:
        root = self.layout.root.resolve(strict=False)
        for process in psutil.process_iter(["exe"]):
            try:
                executable = process.info.get("exe")
                if executable and Path(executable).resolve().is_relative_to(root):
                    return True
            except (OSError, psutil.Error):
                continue
        return False

    def _phase(
        self,
        operation_id: str,
        phase: str,
        message: str,
        *,
        point_of_no_return: bool | None = None,
        invoke_fault: bool = True,
    ) -> None:
        with self.db.session() as session:
            store = OperationStore(session)
            existing = store.get(operation_id)
            next_status = (
                OperationStatus.CANCEL_REQUESTED
                if existing and existing.status == OperationStatus.CANCEL_REQUESTED
                else OperationStatus.RUNNING
            )
            store.transition(
                operation_id,
                status=next_status,
                phase=phase,
                message=message,
                point_of_no_return=point_of_no_return,
            )
            self._record_event_in_session(
                session,
                operation_id,
                "com.aiagentdesktop.operation.progress.v1",
                phase,
                {"phase": phase, "point_of_no_return": bool(point_of_no_return)},
            )
        self.events.emit(
            type_="com.aiagentdesktop.operation.progress.v1",
            subject=f"operation:{operation_id}",
            data={"phase": phase, "message": message},
            resource_ref=ResourceRef(kind="component", id=COMPONENT_ID),
            correlation_id="installer",
            operation_id=operation_id,
        )
        if invoke_fault and self.fault_injector:
            self.fault_injector(phase, operation_id)

    def _complete(self, operation_id: str, *, phase: str, result: dict[str, Any]) -> None:
        with self.db.session() as session:
            OperationStore(session).transition(
                operation_id,
                status=OperationStatus.SUCCEEDED,
                phase=phase,
                message="Operation completed",
                result=redact_value(result),
            )
            self._record_event_in_session(
                session,
                operation_id,
                "com.aiagentdesktop.operation.completed.v1",
                phase,
                {"status": "succeeded"},
            )
        self.events.emit(
            type_="com.aiagentdesktop.operation.completed.v1",
            subject=f"operation:{operation_id}",
            data={"status": "succeeded", "phase": phase},
            resource_ref=ResourceRef(kind="component", id=COMPONENT_ID),
            correlation_id="installer",
            operation_id=operation_id,
        )

    def _cancel(self, operation_id: str, error: InstallerError) -> None:
        user_error = UserFacingError(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            recovery_actions=error.recovery_actions,
            operation_id=operation_id,
        )
        with self.db.session() as session:
            OperationStore(session).transition(
                operation_id,
                status=OperationStatus.CANCELED,
                phase="cancelled",
                message=error.message,
                error=user_error,
            )
            self._record_event_in_session(
                session,
                operation_id,
                "com.aiagentdesktop.operation.completed.v1",
                "cancelled",
                {"status": "canceled"},
            )
        self.events.emit(
            type_="com.aiagentdesktop.operation.completed.v1",
            subject=f"operation:{operation_id}",
            data={"status": "canceled", "phase": "cancelled"},
            resource_ref=ResourceRef(kind="component", id=COMPONENT_ID),
            correlation_id="installer",
            operation_id=operation_id,
        )

    def _fail(self, operation_id: str, error: InstallerError, *, phase: str) -> None:
        diagnostic_id = new_id("diag")
        safe_details = redact_value(error.technical_details)
        user_error = UserFacingError(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            recovery_actions=error.recovery_actions,
            diagnostic_id=diagnostic_id,
            operation_id=operation_id,
        )
        with self.db.session() as session:
            session.add(
                DiagnosticRecord(
                    diagnostic_id=diagnostic_id,
                    severity="error",
                    code=error.code,
                    summary=error.message,
                    user_message=error.message,
                    suggested_actions_json=json.dumps(error.recovery_actions),
                    technical_details_json=json.dumps(safe_details),
                    redaction_applied=1,
                    created_at=utcnow(),
                    correlation_id="installer",
                    operation_id=operation_id,
                    target_kind="component",
                    target_id=COMPONENT_ID,
                )
            )
            OperationStore(session).transition(
                operation_id,
                status=OperationStatus.FAILED,
                phase=phase,
                message=error.message,
                error=user_error,
            )
            self._record_event_in_session(
                session,
                operation_id,
                "com.aiagentdesktop.operation.failed.v1",
                phase,
                {"status": "failed", "code": error.code, "diagnostic_id": diagnostic_id},
            )
        self.events.emit(
            type_="com.aiagentdesktop.operation.failed.v1",
            subject=f"operation:{operation_id}",
            data={"status": "failed", "phase": phase, "code": error.code},
            resource_ref=ResourceRef(kind="component", id=COMPONENT_ID),
            correlation_id="installer",
            operation_id=operation_id,
        )

    def _record_event_in_session(
        self,
        session,
        operation_id: str,
        event_type: str,
        phase: str,
        data: dict[str, Any],
    ) -> None:
        event = OperationEventRecord(
            operation_id=operation_id,
            sequence=0,
            event_type=event_type,
            phase=phase,
            data_json=json.dumps(redact_value(data)),
            created_at=utcnow(),
        )
        session.add(event)
        session.flush()
        event.sequence = event.event_id

    def _check_cancellation(self, operation_id: str) -> None:
        with self.db.session() as session:
            operation = OperationStore(session).get(operation_id)
        if operation is None:
            raise InstallerError("OPERATION_NOT_FOUND", "Installation operation disappeared.")
        if operation.status == OperationStatus.CANCEL_REQUESTED:
            if operation.progress.point_of_no_return:
                return
            raise InstallerCancelled()

    def _remove_path_or_defer(self, path: Path, operation_id: str, reason: str) -> bool:
        if not path.exists():
            return True
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            return True
        except OSError:
            try:
                relative = self.layout.relative(path)
            except InstallerError:
                return False
            now = utcnow()
            with self.db.session() as session:
                existing = session.scalar(
                    select(PendingCleanupRecord).where(
                        PendingCleanupRecord.component_id == COMPONENT_ID,
                        PendingCleanupRecord.relative_path == relative,
                    )
                )
                if existing is None:
                    session.add(
                        PendingCleanupRecord(
                            cleanup_id=new_id("cleanup"),
                            operation_id=operation_id,
                            component_id=COMPONENT_ID,
                            relative_path=relative,
                            reason_code=reason,
                            attempts=0,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                else:
                    existing.operation_id = operation_id
                    existing.reason_code = reason
                    existing.updated_at = now
            self._write_pending_cleanup_state()
            return False

    def _write_pending_cleanup_state(self) -> None:
        if not self.layout.root.exists():
            return
        with self.db.session() as session:
            records = list(session.scalars(select(PendingCleanupRecord)))
        atomic_write_json(
            self.layout.state / "pending-cleanup.json",
            {
                "schema_version": "1.0",
                "items": [
                    {
                        "cleanup_id": item.cleanup_id,
                        "operation_id": item.operation_id,
                        "relative_path": item.relative_path,
                        "reason_code": item.reason_code,
                        "attempts": item.attempts,
                    }
                    for item in records
                ],
            },
        )

    def _release_lease(self, operation_id: str) -> None:
        with self.db.session() as session:
            session.execute(
                delete(InstallationLeaseRecord).where(
                    InstallationLeaseRecord.operation_id == operation_id
                )
            )

    def _is_current_artifact(self, artifact_id: str) -> bool:
        current = self.layout.read_current()
        return bool(current and current.get("artifact_id") == artifact_id)

    def _stage_child(self, operation_id: str, name: str) -> Path:
        if name not in {"acquired", "version", "probe"}:
            raise InstallerError("PATH_IDENTIFIER_INVALID", "Unknown staging path.")
        self.layout.staging_dir(operation_id)
        return self.layout.from_relative(f"staging/{operation_id}/{name}")

    def _current_owned_by_operation(self, operation_id: str) -> bool:
        current = self.layout.read_current()
        return bool(current and current.get("operation_id") == operation_id)

    @staticmethod
    def _target_owned_by_operation(target: Path, operation_id: str) -> bool:
        try:
            record = json.loads((target / "install-record.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False
        return record.get("operation_id") == operation_id

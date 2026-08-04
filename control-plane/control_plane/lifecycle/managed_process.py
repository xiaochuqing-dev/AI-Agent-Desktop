from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import psutil
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from ..application.operation_store import OperationStore
from ..configuration.models import LifecycleOwner, ManagementOwner
from ..configuration.service import CcConnectConfigurationService, canonical_digest
from ..domain.models import Operation, OperationStatus, ResourceRef, UserFacingError
from ..installer.artifacts import InstallerError
from ..installer.paths import ComponentLayout
from ..installer.version_store import ManagedVersionStore
from ..operations import OperationExecutionError, RecoveryDecision
from ..persistence.models import (
    DiagnosticRecord,
    IdempotencyRecord,
    LifecycleEventRecord,
    LifecycleLeaseRecord,
    ManagedProcessRecord,
    OperationEventRecord,
    OwnershipPlanRecord,
    PortOwnershipRecord,
    ProcessIdentityRecord,
)
from ..persistence.session import Database
from ..security.redaction import redact_value
from .models import (
    IdentityVerification,
    LifecycleActionRequest,
    LifecycleRuntimeStatus,
    OwnershipConfirmationRequest,
    OwnershipPlan,
    OwnershipPlanRequest,
    PortOwnershipEvidence,
    ProcessIdentity,
    RuntimeHealth,
)
from .port_ownership import PortOwnershipInspector
from .process_identity import ProcessIdentityInspector

COMPONENT_ID: Literal["cc-connect"] = "cc-connect"
WINDOWS_CREATE_NO_WINDOW = 0x08000000
WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200
TERMINAL_STATUSES = {
    OperationStatus.SUCCEEDED,
    OperationStatus.FAILED,
    OperationStatus.CANCELED,
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _is_expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= utcnow()


Launcher = Callable[..., Any]
ProcessFactory = Callable[[int], Any]


@dataclass(frozen=True)
class RuntimeLaunchConfiguration:
    artifact_id: str
    product_instance_id: str
    configuration_revision: int
    listen_host: Literal["127.0.0.1"]
    listen_port: int
    data_dir: str
    log_dir: str
    project_roots: tuple[str, ...]
    config_path: Path
    legacy_configuration: Any | None = None
    native_runtime: Any | None = None


class ManagedProcessService:
    def __init__(
        self,
        database: Database,
        layout: ComponentLayout,
        configuration_service: CcConnectConfigurationService,
        *,
        version_store: ManagedVersionStore | None = None,
        identity_inspector: ProcessIdentityInspector | None = None,
        port_inspector: PortOwnershipInspector | None = None,
        launcher: Launcher | None = None,
        process_factory: ProcessFactory | None = None,
        external_detector: Callable[[], bool] | None = None,
        native_configuration_service=None,
        runtime_secret_injector=None,
        telegram_identities=None,
        telegram_leases=None,
        external_state_detector=None,
        startup_timeout_seconds: float = 10.0,
        stop_timeout_seconds: float = 5.0,
        stable_window_seconds: float = 3.0,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        self.db = database
        self.layout = layout
        self.configuration_service = configuration_service
        self.version_store = version_store or ManagedVersionStore(layout, database)
        self.identity_inspector = identity_inspector or ProcessIdentityInspector(process_factory)
        self.port_inspector = port_inspector or configuration_service.port_inspector
        self.launcher = launcher or subprocess.Popen
        self.process_factory = process_factory or psutil.Process
        self.native_configuration_service = native_configuration_service
        self.runtime_secret_injector = runtime_secret_injector
        self.telegram_identities = telegram_identities
        self.telegram_leases = telegram_leases
        if external_detector is not None:
            self.external_detector = external_detector
            self.external_state_detector = None
        else:
            if external_state_detector is None:
                from ..cc_connect.external_detection import CcConnectExternalDetector

                external_state_detector = CcConnectExternalDetector(
                    layout.root,
                    port_inspector=self.port_inspector,
                )
            self.external_state_detector = external_state_detector
            self.external_detector = self._external_conflict
        self.startup_timeout_seconds = startup_timeout_seconds
        self.stop_timeout_seconds = stop_timeout_seconds
        self.stable_window_seconds = stable_window_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._launched: dict[int, Any] = {}

    def create_ownership_plan(self, request: OwnershipPlanRequest) -> OwnershipPlan:
        artifact = self.version_store.current()
        management_owner, lifecycle_owner = self.configuration_service.owners()
        external = self.external_detector()
        if external:
            raise InstallerError(
                "EXTERNAL_LIFECYCLE_CONFLICT",
                "External cc-connect state is present; product ownership handoff is blocked.",
                recovery_actions=["stop_or_disambiguate_external_instance", "reprobe_ownership"],
            )
        if lifecycle_owner == LifecycleOwner.PRODUCT:
            raise InstallerError(
                "LIFECYCLE_OWNER_ALREADY_PRODUCT",
                "Product lifecycle ownership is already active.",
                recovery_actions=["read_lifecycle_status"],
            )
        if lifecycle_owner in {
            LifecycleOwner.EXTERNAL,
            LifecycleOwner.CONFLICT,
            LifecycleOwner.UNKNOWN,
        }:
            raise InstallerError(
                "LIFECYCLE_OWNER_HANDOFF_BLOCKED",
                "Current lifecycle ownership cannot be safely handed to the product.",
                recovery_actions=["reprobe_ownership", "resolve_external_conflict"],
            )
        now = utcnow()
        context = self._ownership_context()
        plan = OwnershipPlan(
            plan_id=new_id("owner-plan"),
            plan_digest="sha256:" + "0" * 64,
            context_digest=context,
            artifact_id=artifact.artifact_id,
            current_management_owner=management_owner,
            current_lifecycle_owner=lifecycle_owner,
            external_process_detected=False,
            expected_changes=[
                "assign product lifecycle ownership for the isolated managed version",
                "leave every external process, configuration, task, and watchdog unchanged",
                "do not start cc-connect as part of ownership handoff",
            ],
            rollback_plan=[
                "return lifecycle owner to none only while no managed process is running",
                "leave installed versions and external state unchanged",
            ],
            created_at=now,
            expires_at=now + timedelta(seconds=request.expires_in_seconds),
        )
        plan = plan.model_copy(
            update={
                "plan_digest": canonical_digest(
                    plan.model_dump(mode="json", exclude={"plan_digest"})
                )
            }
        )
        with self.db.session() as session:
            session.add(
                OwnershipPlanRecord(
                    plan_id=plan.plan_id,
                    component_id=COMPONENT_ID,
                    artifact_id=plan.artifact_id,
                    plan_digest=plan.plan_digest,
                    context_digest=plan.context_digest,
                    plan_json=plan.model_dump_json(),
                    status="waiting_for_confirmation",
                    created_at=plan.created_at,
                    expires_at=plan.expires_at,
                    confirmed_at=None,
                    applied_at=None,
                )
            )
        return plan

    def get_ownership_plan(self, plan_id: str) -> OwnershipPlan | None:
        with self.db.session() as session:
            record = session.get(OwnershipPlanRecord, plan_id)
            return OwnershipPlan.model_validate_json(record.plan_json) if record else None

    def confirm_ownership_plan(
        self,
        request: OwnershipConfirmationRequest,
        *,
        idempotency_key: str,
        body: bytes,
    ) -> tuple[Operation, bool]:
        with self.db.session() as session:
            store = OperationStore(session)
            if session.get(IdempotencyRecord, idempotency_key) is not None:
                return store.create(
                    kind="cc_connect_ownership_handoff",
                    target_ref=ResourceRef(kind="component", id=COMPONENT_ID),
                    idempotency_key=idempotency_key,
                    method="POST",
                    resource="/api/v1/components/cc-connect/ownership:confirm",
                    body=body,
                )
            record = session.get(OwnershipPlanRecord, request.plan_id)
            if record is None:
                raise InstallerError(
                    "OWNERSHIP_PLAN_NOT_FOUND",
                    "Lifecycle ownership plan was not found.",
                    recovery_actions=["create_ownership_handoff_plan"],
                )
            plan = OwnershipPlan.model_validate_json(record.plan_json)
            if (
                request.plan_id != plan.plan_id
                or request.plan_digest != plan.plan_digest
                or request.current_management_owner != plan.current_management_owner
                or request.current_lifecycle_owner != plan.current_lifecycle_owner
                or not request.confirmation
            ):
                raise InstallerError(
                    "OWNERSHIP_CONFIRMATION_MISMATCH",
                    "Confirmation is not bound to the immutable ownership plan.",
                    recovery_actions=["review_and_confirm_current_ownership_plan"],
                )
            if record.status != "waiting_for_confirmation":
                raise InstallerError(
                    "OWNERSHIP_PLAN_ALREADY_USED",
                    "Lifecycle ownership plan was already confirmed.",
                    recovery_actions=["create_ownership_handoff_plan"],
                )
            self._validate_ownership_context(plan)
            operation, reused = store.create(
                kind="cc_connect_ownership_handoff",
                target_ref=ResourceRef(kind="component", id=COMPONENT_ID),
                idempotency_key=idempotency_key,
                method="POST",
                resource="/api/v1/components/cc-connect/ownership:confirm",
                body=body,
            )
            record.status = "confirmed"
            record.confirmed_at = utcnow()
            return operation, reused

    def execute_ownership_handoff(self, operation_id: str, plan_id: str) -> dict[str, Any] | None:
        try:
            with self.db.session() as session:
                record = session.get(OwnershipPlanRecord, plan_id)
                if record is None or record.status != "confirmed":
                    raise InstallerError(
                        "OWNERSHIP_PLAN_NOT_CONFIRMED",
                        "Lifecycle ownership plan is missing or not confirmed.",
                        recovery_actions=["create_ownership_handoff_plan"],
                    )
                plan = OwnershipPlan.model_validate_json(record.plan_json)
                expected = canonical_digest(plan.model_dump(mode="json", exclude={"plan_digest"}))
                if expected != plan.plan_digest or expected != record.plan_digest:
                    raise InstallerError(
                        "OWNERSHIP_PLAN_TAMPERED",
                        "Persisted lifecycle ownership plan was modified.",
                        recovery_actions=["create_ownership_handoff_plan"],
                    )
            self._check_cancellation(operation_id)
            self._validate_ownership_context(plan)
            artifact = self.version_store.current()
            now = utcnow()
            with self.db.session() as session:
                managed = session.get(ManagedProcessRecord, COMPONENT_ID)
                if managed is None:
                    managed = ManagedProcessRecord(
                        component_id=COMPONENT_ID,
                        product_instance_id=self.configuration_service.product_instance_id,
                        artifact_id=artifact.artifact_id,
                        configuration_revision=0,
                        pid=None,
                        process_create_time=None,
                        expected_state="stopped",
                        observed_state="unconfigured",
                        management_owner=ManagementOwner.PRODUCT.value,
                        lifecycle_owner=LifecycleOwner.PRODUCT.value,
                        identity_json=None,
                        health_json=None,
                        last_operation_id=operation_id,
                        last_exit_code=None,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(managed)
                else:
                    if managed.pid is not None:
                        raise InstallerError(
                            "OWNERSHIP_HANDOFF_PROCESS_CONFLICT",
                            "Ownership cannot change while a managed PID is recorded.",
                            recovery_actions=["reconcile_lifecycle"],
                        )
                    managed.artifact_id = artifact.artifact_id
                    managed.management_owner = ManagementOwner.PRODUCT.value
                    managed.lifecycle_owner = LifecycleOwner.PRODUCT.value
                    managed.last_operation_id = operation_id
                    managed.updated_at = now
                record = session.get(OwnershipPlanRecord, plan_id)
                assert record is not None
                record.status = "applied"
                record.applied_at = now
            result = {
                "component_id": COMPONENT_ID,
                "management_owner": "product",
                "lifecycle_owner": "product",
                "process_started": False,
                "external_state_modified": False,
            }
            self._complete_operation(
                operation_id,
                phase="ownership_handoff_applied",
                message="Product lifecycle ownership was assigned without starting a process.",
                result=result,
            )
            return result
        except InstallerError as exc:
            self._fail_operation(operation_id, exc, phase="ownership_handoff_failed")
            return None

    def create_operation(
        self,
        action: Literal["start", "stop", "restart", "reconcile", "health"],
        request: LifecycleActionRequest,
        *,
        idempotency_key: str,
        body: bytes,
    ) -> tuple[Operation, bool]:
        resource = f"/api/v1/components/cc-connect:{action}"
        try:
            with self.db.session() as session:
                store = OperationStore(session)
                if session.get(IdempotencyRecord, idempotency_key) is not None:
                    return store.create(
                        kind=f"cc_connect_lifecycle_{action}",
                        target_ref=ResourceRef(kind="component", id=COMPONENT_ID),
                        idempotency_key=idempotency_key,
                        method="POST",
                        resource=resource,
                        body=body,
                    )
                lease = session.get(LifecycleLeaseRecord, COMPONENT_ID)
                if lease is not None:
                    raise InstallerError(
                        "LIFECYCLE_OPERATION_ALREADY_RUNNING",
                        "Another product lifecycle operation owns the component lease.",
                        retryable=True,
                        recovery_actions=["wait_for_active_operation"],
                    )
                operation, reused = store.create(
                    kind=f"cc_connect_lifecycle_{action}",
                    target_ref=ResourceRef(kind="component", id=COMPONENT_ID),
                    idempotency_key=idempotency_key,
                    method="POST",
                    resource=resource,
                    body=body,
                )
                session.add(
                    LifecycleLeaseRecord(
                        component_id=COMPONENT_ID,
                        operation_id=operation.operation_id,
                        owner="product",
                        action=action,
                        acquired_at=utcnow(),
                    )
                )
                return operation, reused
        except IntegrityError:
            raise InstallerError(
                "LIFECYCLE_OPERATION_ALREADY_RUNNING",
                "Another product lifecycle operation acquired the component lease.",
                retryable=True,
                recovery_actions=["wait_for_active_operation"],
            ) from None

    def execute_action(
        self,
        operation_id: str,
        action: Literal["start", "stop", "restart", "reconcile", "health"],
        request: LifecycleActionRequest,
    ) -> dict[str, Any] | None:
        try:
            self._check_cancellation(operation_id)
            if action == "start":
                result = self._start(operation_id, request.configuration_revision)
            elif action == "stop":
                result = self._stop(operation_id, request.configuration_revision)
            elif action == "restart":
                self._stop(operation_id, request.configuration_revision, for_restart=True)
                result = self._start(operation_id, request.configuration_revision, for_restart=True)
            else:
                status = self.reconcile(operation_id=operation_id)
                result = status.model_dump(mode="json")
            self._complete_operation(
                operation_id,
                phase=f"lifecycle_{action}_completed",
                message=f"Product-managed cc-connect {action} completed.",
                result=result,
            )
            return result
        except InstallerError as exc:
            self._fail_operation(operation_id, exc, phase=f"lifecycle_{action}_failed")
            return None
        finally:
            self._release_lease(operation_id)

    def reconcile(self, *, operation_id: str = "startup-reconcile") -> LifecycleRuntimeStatus:
        with self.db.session() as session:
            record = session.get(ManagedProcessRecord, COMPONENT_ID)
        if record is None:
            management, lifecycle = self.configuration_service.owners()
            return self._empty_status(management, lifecycle)
        management = self._management_owner(record.management_owner)
        lifecycle = self._lifecycle_owner(record.lifecycle_owner)
        if record.pid is None or not record.identity_json:
            if record.configuration_revision == 0:
                observed = "unconfigured"
                health = self._stopped_health()
            elif record.expected_state == "running" and record.observed_state == "crashed":
                observed = "crashed"
                health = RuntimeHealth(
                    overall="unhealthy",
                    process_identity_verified=False,
                    artifact_integrity_verified=True,
                    configuration_revision_verified=True,
                    port_owned_by_process=False,
                    startup_stable_for_window=False,
                )
            else:
                observed = "stopped"
                health = self._stopped_health()
            self._update_observation(record, observed, health, pid=None)
            if observed in {"stopped", "crashed", "unconfigured"}:
                self._release_runtime_leases(f"reconcile_{observed}")
            return self._status_from_record(record, health=health)
        identity = ProcessIdentity.model_validate_json(record.identity_json)
        verification = self.identity_inspector.verify(identity)
        if verification.status == "missing":
            exit_code = self._poll_exit_code(identity.pid)
            observed = "crashed" if record.expected_state == "running" else "stopped"
            health = RuntimeHealth(
                overall="unhealthy" if observed == "crashed" else "stopped",
                process_identity_verified=False,
                artifact_integrity_verified=False,
                configuration_revision_verified=False,
                port_owned_by_process=False,
                startup_stable_for_window=False,
            )
            self._update_observation(
                record,
                observed,
                health,
                pid=None,
                last_exit_code=exit_code,
            )
            self._release_runtime_leases("process_missing")
            return self._status_from_record(
                record,
                verification=verification,
                health=health,
                identity=identity,
            )
        if verification.status != "verified":
            health = RuntimeHealth(
                overall="unhealthy",
                process_identity_verified=False,
                artifact_integrity_verified=False,
                configuration_revision_verified=False,
                port_owned_by_process=False,
                startup_stable_for_window=False,
            )
            self._update_observation(record, "conflict", health)
            return self._status_from_record(
                record,
                verification=verification,
                health=health,
                identity=identity,
            )
        artifact_verified = self._artifact_matches(identity)
        configuration_verified = self._configuration_matches(identity)
        port = self.port_inspector.inspect(
            identity.listen_host, identity.listen_port, expected_pid=identity.pid
        )
        port_verified = port.status == "owned"
        stable = self._stable_since(identity.process_create_time)
        management_api_verified = False
        management_api_status: Literal[
            "not_checked", "verified", "auth_failed", "unreachable", "unsupported"
        ] = "not_checked"
        update_owner_verified = True
        native_runtime = None
        if self.native_configuration_service is not None:
            native_state = self.native_configuration_service.state()
            if (
                native_state.status == "valid"
                and native_state.revision == identity.configuration_revision
                and native_state.runtime_config is not None
            ):
                native_runtime = native_state.runtime_config
                if self.runtime_secret_injector is not None:
                    management_api_status = self.runtime_secret_injector.probe_management_status(
                        native_runtime
                    )
                    management_api_verified = management_api_status == "verified"
                if self.telegram_leases is not None and self.telegram_identities is not None:
                    revisions = self._runtime_credential_revisions()
                    try:
                        self.telegram_leases.acquire_runtime(
                            ["claude", "codex"],
                            identity.operation_id,
                            credential_revisions=revisions,
                        )
                    except OperationExecutionError:
                        update_owner_verified = False
        healthy_partial = (
            artifact_verified
            and configuration_verified
            and port_verified
            and stable
            and update_owner_verified
        )
        health = RuntimeHealth(
            overall="partial" if healthy_partial else "unhealthy",
            process_identity_verified=True,
            artifact_integrity_verified=artifact_verified,
            configuration_revision_verified=configuration_verified,
            port_owned_by_process=port_verified,
            startup_stable_for_window=stable,
            fatal_log_detected=self._fatal_log_detected(),
            management_api_verified=management_api_verified,
            management_api_status=management_api_status,
            management_api_bind_scope=(
                "upstream_all_interfaces" if native_runtime is not None else "unknown"
            ),
        )
        observed = (
            "running_partial" if healthy_partial and not health.fatal_log_detected else "conflict"
        )
        self._update_observation(record, observed, health)
        self._record_port(operation_id, port)
        return self._status_from_record(
            record,
            verification=verification,
            port=port,
            health=health,
            identity=identity,
        )

    def status(self) -> LifecycleRuntimeStatus:
        return self.reconcile(operation_id="status-probe")

    def recovery_probe(self, operation_id: str, payload: dict[str, Any]) -> RecoveryDecision:
        action = str(payload.get("action", ""))
        if action == "ownership_handoff":
            plan_id = str(payload.get("plan_id", ""))
            with self.db.session() as session:
                plan = session.get(OwnershipPlanRecord, plan_id)
            if plan is not None and plan.status == "applied":
                return RecoveryDecision.complete(
                    {"management_owner": "product", "lifecycle_owner": "product"}
                )
            if plan is not None and plan.status == "confirmed":
                try:
                    self._validate_ownership_context(
                        OwnershipPlan.model_validate_json(plan.plan_json)
                    )
                    return RecoveryDecision.requeue()
                except InstallerError as exc:
                    return RecoveryDecision.fail(
                        code=exc.code,
                        message=exc.message,
                        recovery_actions=exc.recovery_actions,
                    )
            return RecoveryDecision.fail(code="OWNERSHIP_RECOVERY_STATE_CONFLICT")
        status = self.status()
        if action == "start":
            if status.observed_state == "running_partial":
                return RecoveryDecision.complete(status.model_dump(mode="json"))
            if status.observed_state in {"stopped", "unconfigured"}:
                return RecoveryDecision.requeue()
        elif action == "stop":
            if status.observed_state in {"stopped", "unconfigured", "crashed"}:
                return RecoveryDecision.complete(status.model_dump(mode="json"))
            if status.identity_verification and status.identity_verification.status == "verified":
                return RecoveryDecision.requeue()
        elif action == "reconcile":
            return RecoveryDecision.requeue()
        elif action == "restart" and (
            status.observed_state == "running_partial"
            and status.identity is not None
            and status.identity.operation_id == operation_id
        ):
            return RecoveryDecision.complete(status.model_dump(mode="json"))
        return RecoveryDecision.fail(code="LIFECYCLE_RECOVERY_REQUIRES_REVIEW")

    def recover_leases(self) -> None:
        with self.db.session() as session:
            leases = list(session.scalars(select(LifecycleLeaseRecord)))
            for lease in leases:
                operation = OperationStore(session).get(lease.operation_id)
                if operation is None or operation.status in TERMINAL_STATUSES:
                    session.delete(lease)

    def _start(
        self, operation_id: str, expected_revision: int, *, for_restart: bool = False
    ) -> dict[str, Any]:
        self._phase(
            operation_id, "start_preflight", "Verifying artifact, configuration, owners, and port"
        )
        artifact = self.version_store.current()
        configuration = self._resolve_launch_configuration(expected_revision)
        if (
            configuration.artifact_id != artifact.artifact_id
            or configuration.product_instance_id != self.configuration_service.product_instance_id
        ):
            raise InstallerError(
                "LIFECYCLE_CONFIGURATION_IDENTITY_MISMATCH",
                "Configuration is not bound to the active artifact and product instance.",
                recovery_actions=["create_configuration_plan"],
            )
        management, lifecycle = self.configuration_service.owners()
        if management != ManagementOwner.PRODUCT or lifecycle != LifecycleOwner.PRODUCT:
            raise InstallerError(
                "LIFECYCLE_OWNER_NOT_PRODUCT",
                "Start is allowed only for explicit product lifecycle ownership.",
                recovery_actions=["create_ownership_handoff_plan"],
            )
        if self.external_detector():
            raise InstallerError(
                "EXTERNAL_LIFECYCLE_CONFLICT",
                "External cc-connect process or executable state blocks product start.",
                recovery_actions=["resolve_external_conflict", "reprobe_ownership"],
            )
        existing = self.status()
        if existing.observed_state == "running_partial":
            if existing.configuration_revision != expected_revision:
                raise InstallerError(
                    "CONFIGURATION_REVISION_CONFLICT",
                    "Running process uses a different configuration revision.",
                    recovery_actions=["restart_with_active_revision"],
                )
            return {**existing.model_dump(mode="json"), "already_running": True}
        if existing.observed_state == "conflict":
            raise InstallerError(
                "MANAGED_PROCESS_IDENTITY_CONFLICT",
                "Recorded process identity cannot be proven; start was refused.",
                recovery_actions=["reconcile_lifecycle", "inspect_process_identity"],
            )
        if not self.port_inspector.is_available(
            configuration.listen_host, configuration.listen_port
        ):
            evidence = self.port_inspector.inspect(
                configuration.listen_host, configuration.listen_port
            )
            self._record_port(operation_id, evidence)
            raise InstallerError(
                "MANAGED_PORT_CONFLICT",
                "Confirmed loopback port is occupied; no process was started.",
                retryable=True,
                recovery_actions=["stop_port_owner_or_create_new_configuration_plan"],
                technical_details={"listen_port": configuration.listen_port},
            )
        if configuration.native_runtime is not None:
            assert self.native_configuration_service is not None
            native_state = self.native_configuration_service.state()
            assert native_state.managed_state is not None
            self.native_configuration_service.validate_runtime_prerequisites(
                configuration.native_runtime,
                native_state.managed_state,
            )
        else:
            assert configuration.legacy_configuration is not None
            self.configuration_service.validate_runtime_prerequisites(
                configuration.legacy_configuration
            )
        managed_directories = [configuration.data_dir, configuration.log_dir]
        if configuration.legacy_configuration is not None:
            managed_directories.extend(configuration.project_roots)
        for directory in managed_directories:
            target = Path(directory)
            if not target.resolve(strict=False).is_relative_to(self.layout.root.resolve(False)):
                raise InstallerError(
                    "LIFECYCLE_PATH_ESCAPE_BLOCKED",
                    "Runtime directory escaped the product-managed root.",
                    recovery_actions=["create_configuration_plan"],
                )
            target.mkdir(parents=True, exist_ok=True)
        self._check_cancellation(operation_id)
        arguments = [
            str(artifact.executable),
            "-config",
            str(configuration.config_path),
        ]
        runtime_leases_acquired = False
        if configuration.native_runtime is not None:
            if (
                self.telegram_identities is None
                or self.telegram_leases is None
                or self.runtime_secret_injector is None
            ):
                raise InstallerError(
                    "TELEGRAM_RUNTIME_GUARD_UNAVAILABLE",
                    "Telegram identity, secret injection, or update-owner guards are unavailable.",
                    recovery_actions=["restart_control_plane"],
                )
            self.telegram_identities.assert_no_webhook(["claude", "codex"])
            self.telegram_leases.acquire_runtime(
                ["claude", "codex"],
                operation_id,
                credential_revisions=self._runtime_credential_revisions(),
            )
            runtime_leases_acquired = True
        environment_context = (
            self.runtime_secret_injector.environment(
                configuration.native_runtime,
                operation_id=operation_id,
                product_instance_id=configuration.product_instance_id,
            )
            if configuration.native_runtime is not None and self.runtime_secret_injector is not None
            else nullcontext(self._safe_environment(configuration.listen_port))
        )
        log_path = self._rotate_log(Path(configuration.log_dir) / "cc-connect-runtime.log")
        creationflags = (
            WINDOWS_CREATE_NO_WINDOW | WINDOWS_CREATE_NEW_PROCESS_GROUP
            if sys.platform == "win32"
            else 0
        )
        self._phase(
            operation_id,
            "starting_process",
            "Launching product-managed cc-connect without a visible console",
            point_of_no_return=True,
        )
        try:
            with environment_context as environment:
                with log_path.open("ab", buffering=0) as log_handle:
                    process = self.launcher(
                        arguments,
                        cwd=str(artifact.executable.parent),
                        env=environment,
                        stdin=subprocess.DEVNULL,
                        stdout=log_handle,
                        stderr=subprocess.STDOUT,
                        shell=False,
                        creationflags=creationflags,
                        close_fds=True,
                    )
        except OSError as exc:
            if runtime_leases_acquired:
                self._release_runtime_leases("launch_failed")
            raise InstallerError(
                "MANAGED_PROCESS_LAUNCH_FAILED",
                "Product-managed cc-connect could not be launched.",
                retryable=True,
                recovery_actions=["inspect_startup_log", "verify_artifact_permissions"],
                technical_details={"error": type(exc).__name__},
            ) from None
        pid = int(process.pid)
        self._launched[pid] = process
        try:
            identity = self.identity_inspector.capture(
                pid=pid,
                expected_executable=artifact.executable,
                expected_sha256=artifact.artifact_sha256,
                expected_arguments=arguments,
                component_id=COMPONENT_ID,
                product_instance_id=configuration.product_instance_id,
                artifact_id=artifact.artifact_id,
                configuration_revision=configuration.configuration_revision,
                listen_host=configuration.listen_host,
                listen_port=configuration.listen_port,
                operation_id=operation_id,
            )
        except InstallerError as exc:
            exit_code = self._poll_exit_code(pid)
            self._terminate_launch_handle(process)
            self._persist_launch_failure(
                operation_id,
                artifact.artifact_id,
                configuration.configuration_revision,
                exit_code,
            )
            if runtime_leases_acquired:
                self._release_runtime_leases("identity_capture_failed")
            if (
                exit_code is not None
                and configuration.legacy_configuration is not None
                and configuration.legacy_configuration.telegram.enabled is False
            ):
                raise InstallerError(
                    "CC_CONNECT_SECRETLESS_RUNTIME_UNSUPPORTED",
                    "Locked cc-connect exited because its upstream runtime has no sustained secretless Telegram-disabled mode.",
                    recovery_actions=[
                        "keep_runtime_stopped",
                        "continue_future_secret_binding_slice",
                    ],
                    technical_details={"exit_code": exit_code},
                ) from None
            raise exc
        self._persist_started(identity)
        deadline = time.monotonic() + self.startup_timeout_seconds
        stable_since: float | None = None
        last_port = PortOwnershipEvidence(
            listen_port=configuration.listen_port,
            status="not_listening",
            expected_pid=pid,
        )
        while time.monotonic() < deadline:
            exit_code = self._poll_exit_code(pid)
            if exit_code is not None:
                self._persist_crash(identity, exit_code)
                if runtime_leases_acquired:
                    self._release_runtime_leases("startup_exit")
                raise InstallerError(
                    "MANAGED_PROCESS_EXITED_DURING_STARTUP",
                    "cc-connect exited before local runtime evidence became stable.",
                    retryable=True,
                    recovery_actions=["inspect_startup_log", "retry_after_review"],
                    technical_details={"exit_code": exit_code},
                )
            last_port = self.port_inspector.inspect(
                configuration.listen_host, configuration.listen_port, expected_pid=pid
            )
            if last_port.status == "conflict":
                self._stop_verified_identity(identity)
                if runtime_leases_acquired:
                    self._release_runtime_leases("startup_port_conflict")
                self._record_port(operation_id, last_port)
                raise InstallerError(
                    "MANAGED_PORT_OWNED_BY_OTHER_PID",
                    "Target port is not owned by the launched process.",
                    recovery_actions=["inspect_port_owner", "create_new_configuration_plan"],
                )
            if last_port.status == "owned":
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= self.stable_window_seconds:
                    break
            else:
                stable_since = None
            time.sleep(self.poll_interval_seconds)
        else:
            self._stop_verified_identity(identity)
            if runtime_leases_acquired:
                self._release_runtime_leases("startup_timeout")
            self._record_port(operation_id, last_port)
            raise InstallerError(
                "MANAGED_PROCESS_STARTUP_TIMEOUT",
                "cc-connect did not prove target-port ownership within the startup timeout.",
                retryable=True,
                recovery_actions=["inspect_startup_log", "review_upstream_runtime_capability"],
            )
        management_api_verified = False
        management_api_status: Literal[
            "not_checked", "verified", "auth_failed", "unreachable", "unsupported"
        ] = "not_checked"
        if configuration.native_runtime is not None and self.runtime_secret_injector is not None:
            management_api_status = self.runtime_secret_injector.probe_management_status(
                configuration.native_runtime
            )
            management_api_verified = management_api_status == "verified"
        health = RuntimeHealth(
            overall="partial",
            process_identity_verified=True,
            artifact_integrity_verified=True,
            configuration_revision_verified=True,
            port_owned_by_process=True,
            startup_stable_for_window=True,
            fatal_log_detected=self._fatal_log_detected(),
            management_api_verified=management_api_verified,
            management_api_status=management_api_status,
            management_api_bind_scope=(
                "upstream_all_interfaces" if configuration.native_runtime is not None else "unknown"
            ),
        )
        if health.fatal_log_detected:
            self._stop_verified_identity(identity)
            if runtime_leases_acquired:
                self._release_runtime_leases("fatal_startup_log")
            raise InstallerError(
                "MANAGED_PROCESS_FATAL_STARTUP_LOG",
                "Startup log contains a fatal marker; running state was not reported.",
                recovery_actions=["inspect_redacted_startup_log"],
            )
        self._update_running(identity, health)
        self._record_port(operation_id, last_port)
        return {
            "component_id": COMPONENT_ID,
            "pid": pid,
            "process_create_time": identity.process_create_time,
            "artifact_id": identity.artifact_id,
            "configuration_revision": identity.configuration_revision,
            "listen_host": identity.listen_host,
            "listen_port": identity.listen_port,
            "health": "partial",
            "deep_health": "unsupported",
            "management_api_verified": management_api_verified,
            "management_api_bind_scope": health.management_api_bind_scope,
            "restart": for_restart,
        }

    def _stop(
        self,
        operation_id: str,
        expected_revision: int,
        *,
        for_restart: bool = False,
    ) -> dict[str, Any]:
        self._phase(
            operation_id, "stop_preflight", "Verifying recorded process identity before stop"
        )
        with self.db.session() as session:
            record = session.get(ManagedProcessRecord, COMPONENT_ID)
        if record is None or record.pid is None or not record.identity_json:
            if record is not None:
                health = self._stopped_health()
                self._update_observation(record, "stopped", health, pid=None)
            self._release_runtime_leases("already_stopped")
            return {"component_id": COMPONENT_ID, "already_stopped": True, "restart": for_restart}
        if record.lifecycle_owner != LifecycleOwner.PRODUCT.value:
            raise InstallerError(
                "EXTERNAL_LIFECYCLE_OWNER_BLOCKED",
                "Stop is forbidden because lifecycle ownership is not product.",
                recovery_actions=["reprobe_ownership"],
            )
        identity = ProcessIdentity.model_validate_json(record.identity_json)
        if identity.configuration_revision != expected_revision:
            raise InstallerError(
                "CONFIGURATION_REVISION_CONFLICT",
                "Stop confirmation revision does not match the recorded process identity.",
                recovery_actions=["read_lifecycle_status", "retry_with_active_revision"],
            )
        verification = self.identity_inspector.verify(identity)
        if verification.status == "missing":
            self._persist_crash(identity, self._poll_exit_code(identity.pid))
            self._release_runtime_leases("process_missing_during_stop")
            return {
                "component_id": COMPONENT_ID,
                "already_stopped": True,
                "previous_process_missing": True,
                "restart": for_restart,
            }
        if verification.status != "verified":
            self._persist_conflict(record, verification)
            raise InstallerError(
                verification.diagnostic_code or "MANAGED_PROCESS_IDENTITY_MISMATCH",
                "Recorded PID does not match the product process; no process was stopped.",
                recovery_actions=["inspect_process_identity", "reconcile_lifecycle"],
            )
        self._check_cancellation(operation_id)
        self._phase(
            operation_id,
            "stopping_process",
            "Stopping only the identity-verified product process tree",
            point_of_no_return=True,
        )
        forced = self._terminate_verified_tree(identity)
        deadline = time.monotonic() + self.stop_timeout_seconds
        port = self.port_inspector.inspect(
            identity.listen_host, identity.listen_port, expected_pid=identity.pid
        )
        while port.status == "owned" and time.monotonic() < deadline:
            time.sleep(self.poll_interval_seconds)
            port = self.port_inspector.inspect(
                identity.listen_host, identity.listen_port, expected_pid=identity.pid
            )
        if port.status == "owned":
            raise InstallerError(
                "MANAGED_PORT_RELEASE_TIMEOUT",
                "Identity-verified process stopped but its port was not proven released.",
                retryable=True,
                recovery_actions=["reconcile_lifecycle", "inspect_port_owner"],
            )
        self._record_port(operation_id, port)
        with self.db.session() as session:
            managed = session.get(ManagedProcessRecord, COMPONENT_ID)
            assert managed is not None
            managed.pid = None
            managed.process_create_time = None
            managed.identity_json = None
            managed.expected_state = "stopped" if not for_restart else "running"
            managed.observed_state = "stopped"
            managed.health_json = self._stopped_health().model_dump_json()
            managed.last_operation_id = operation_id
            managed.last_exit_code = self._poll_exit_code(identity.pid)
            managed.updated_at = utcnow()
        self._launched.pop(identity.pid, None)
        self._release_runtime_leases("managed_runtime_stopped")
        return {
            "component_id": COMPONENT_ID,
            "stopped": True,
            "forced_termination": forced,
            "port_released": port.status != "owned",
            "restart": for_restart,
        }

    def _terminate_verified_tree(self, identity: ProcessIdentity) -> bool:
        verification = self.identity_inspector.verify(identity)
        if verification.status != "verified":
            raise InstallerError(
                "MANAGED_PROCESS_IDENTITY_CHANGED_BEFORE_STOP",
                "Process identity changed between stop preflight and signal delivery.",
                recovery_actions=["reconcile_lifecycle"],
            )
        try:
            process = self.process_factory(identity.pid)
            children = list(process.children(recursive=True))
        except psutil.NoSuchProcess:
            return False
        except (OSError, psutil.AccessDenied):
            raise InstallerError(
                "MANAGED_PROCESS_TREE_INACCESSIBLE",
                "Current user cannot enumerate the verified managed process tree.",
                recovery_actions=["inspect_current_user_permissions"],
            ) from None
        try:
            if sys.platform == "win32":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.send_signal(signal.SIGTERM)
            process.wait(timeout=self.stop_timeout_seconds)
            return False
        except (psutil.TimeoutExpired, subprocess.TimeoutExpired):
            pass
        except (OSError, psutil.Error):
            try:
                process.terminate()
                process.wait(timeout=self.stop_timeout_seconds)
                return False
            except (OSError, psutil.Error, subprocess.TimeoutExpired):
                pass
        targets = [*children, process]
        for target in targets:
            try:
                target.terminate()
            except psutil.NoSuchProcess:
                continue
        _gone, alive = psutil.wait_procs(targets, timeout=self.stop_timeout_seconds)
        for target in alive:
            try:
                target.kill()
            except psutil.NoSuchProcess:
                continue
        _gone, alive = psutil.wait_procs(alive, timeout=self.stop_timeout_seconds)
        if alive:
            raise InstallerError(
                "MANAGED_PROCESS_STOP_TIMEOUT",
                "Verified product process tree remained after forced termination.",
                retryable=True,
                recovery_actions=["reconcile_lifecycle", "inspect_process_tree"],
            )
        return True

    def _persist_started(self, identity: ProcessIdentity) -> None:
        now = utcnow()
        health = RuntimeHealth(
            overall="starting",
            process_identity_verified=True,
            artifact_integrity_verified=True,
            configuration_revision_verified=True,
            port_owned_by_process=False,
            startup_stable_for_window=False,
        )
        with self.db.session() as session:
            managed = session.get(ManagedProcessRecord, COMPONENT_ID)
            if managed is None:
                raise InstallerError(
                    "LIFECYCLE_OWNER_RECORD_MISSING",
                    "Product lifecycle ownership record disappeared before launch persistence.",
                    recovery_actions=["reconcile_lifecycle"],
                )
            managed.artifact_id = identity.artifact_id
            managed.configuration_revision = identity.configuration_revision
            managed.pid = identity.pid
            managed.process_create_time = identity.process_create_time
            managed.expected_state = "running"
            managed.observed_state = "starting"
            managed.identity_json = identity.model_dump_json()
            managed.health_json = health.model_dump_json()
            managed.last_operation_id = identity.operation_id
            managed.last_exit_code = None
            managed.updated_at = now
            session.add(
                ProcessIdentityRecord(
                    identity_id=new_id("identity"),
                    component_id=COMPONENT_ID,
                    operation_id=identity.operation_id,
                    pid=identity.pid,
                    process_create_time=identity.process_create_time,
                    identity_json=identity.model_dump_json(),
                    verification_status="verified",
                    created_at=now,
                )
            )

    def _update_running(self, identity: ProcessIdentity, health: RuntimeHealth) -> None:
        with self.db.session() as session:
            record = session.get(ManagedProcessRecord, COMPONENT_ID)
            assert record is not None
            record.expected_state = "running"
            record.observed_state = "running_partial"
            record.health_json = health.model_dump_json()
            record.last_operation_id = identity.operation_id
            record.updated_at = utcnow()

    def _persist_launch_failure(
        self,
        operation_id: str,
        artifact_id: str,
        configuration_revision: int,
        exit_code: int | None,
    ) -> None:
        with self.db.session() as session:
            record = session.get(ManagedProcessRecord, COMPONENT_ID)
            if record is None:
                return
            record.artifact_id = artifact_id
            record.configuration_revision = configuration_revision
            record.pid = None
            record.process_create_time = None
            record.expected_state = "running"
            record.observed_state = "crashed"
            record.identity_json = None
            record.health_json = RuntimeHealth(
                overall="unhealthy",
                process_identity_verified=False,
                artifact_integrity_verified=True,
                configuration_revision_verified=True,
                port_owned_by_process=False,
                startup_stable_for_window=False,
            ).model_dump_json()
            record.last_operation_id = operation_id
            record.last_exit_code = exit_code
            record.updated_at = utcnow()

    def _persist_crash(self, identity: ProcessIdentity, exit_code: int | None) -> None:
        self._persist_launch_failure(
            identity.operation_id,
            identity.artifact_id,
            identity.configuration_revision,
            exit_code,
        )
        self._launched.pop(identity.pid, None)

    def _persist_conflict(
        self, record: ManagedProcessRecord, verification: IdentityVerification
    ) -> None:
        health = RuntimeHealth(
            overall="unhealthy",
            process_identity_verified=False,
            artifact_integrity_verified=False,
            configuration_revision_verified=False,
            port_owned_by_process=False,
            startup_stable_for_window=False,
        )
        self._update_observation(record, "conflict", health)
        with self.db.session() as session:
            session.add(
                ProcessIdentityRecord(
                    identity_id=new_id("identity"),
                    component_id=COMPONENT_ID,
                    operation_id=record.last_operation_id or "reconcile",
                    pid=record.pid or 0,
                    process_create_time=record.process_create_time or "unknown",
                    identity_json=record.identity_json or "{}",
                    verification_status=verification.status,
                    created_at=utcnow(),
                )
            )

    def _update_observation(
        self,
        original: ManagedProcessRecord,
        observed_state: str,
        health: RuntimeHealth,
        *,
        pid: int | None | object = ...,
        last_exit_code: int | None | object = ...,
    ) -> None:
        with self.db.session() as session:
            record = session.get(ManagedProcessRecord, COMPONENT_ID)
            if record is None:
                return
            record.observed_state = observed_state
            record.health_json = health.model_dump_json()
            if pid is not ...:
                record.pid = pid  # type: ignore[assignment]
                if pid is None:
                    record.process_create_time = None
            if last_exit_code is not ...:
                record.last_exit_code = last_exit_code  # type: ignore[assignment]
            record.updated_at = utcnow()
        original.observed_state = observed_state
        original.health_json = health.model_dump_json()
        if pid is not ...:
            original.pid = pid  # type: ignore[assignment]
        if last_exit_code is not ...:
            original.last_exit_code = last_exit_code  # type: ignore[assignment]
        original.updated_at = utcnow()

    def _status_from_record(
        self,
        record: ManagedProcessRecord,
        *,
        verification: IdentityVerification | None = None,
        port: PortOwnershipEvidence | None = None,
        health: RuntimeHealth | None = None,
        identity: ProcessIdentity | None = None,
    ) -> LifecycleRuntimeStatus:
        if identity is None and record.identity_json:
            try:
                identity = ProcessIdentity.model_validate_json(record.identity_json)
            except ValueError:
                identity = None
        if health is None and record.health_json:
            try:
                health = RuntimeHealth.model_validate_json(record.health_json)
            except ValueError:
                health = None
        return LifecycleRuntimeStatus(
            product_instance_id=record.product_instance_id,
            artifact_id=record.artifact_id,
            configuration_revision=record.configuration_revision,
            expected_state=("running" if record.expected_state == "running" else "stopped"),
            observed_state=self._observed_state(record.observed_state),
            management_owner=self._management_owner(record.management_owner),
            lifecycle_owner=self._lifecycle_owner(record.lifecycle_owner),
            pid=record.pid,
            identity=identity,
            identity_verification=verification,
            port_ownership=port,
            health=health or self._stopped_health(),
            last_exit_code=record.last_exit_code,
            updated_at=record.updated_at,
        )

    def _empty_status(
        self, management: ManagementOwner, lifecycle: LifecycleOwner
    ) -> LifecycleRuntimeStatus:
        return LifecycleRuntimeStatus(
            expected_state="stopped",
            observed_state="unconfigured",
            management_owner=management,
            lifecycle_owner=lifecycle,
            health=self._stopped_health(),
            updated_at=utcnow(),
        )

    @staticmethod
    def _stopped_health() -> RuntimeHealth:
        return RuntimeHealth(
            overall="stopped",
            process_identity_verified=False,
            artifact_integrity_verified=False,
            configuration_revision_verified=False,
            port_owned_by_process=False,
            startup_stable_for_window=False,
        )

    def _resolve_launch_configuration(self, expected_revision: int) -> RuntimeLaunchConfiguration:
        if self.native_configuration_service is not None:
            native_state = self.native_configuration_service.state()
            if native_state.status != "missing":
                runtime, managed = self.native_configuration_service.runtime_for_start(
                    expected_revision
                )
                return RuntimeLaunchConfiguration(
                    artifact_id=managed.artifact_id,
                    product_instance_id=managed.product_instance_id,
                    configuration_revision=managed.configuration_revision,
                    listen_host="127.0.0.1",
                    listen_port=runtime.management_port,
                    data_dir=runtime.data_dir,
                    log_dir=runtime.log_dir,
                    project_roots=tuple(project.workspace_root for project in runtime.projects),
                    config_path=self.native_configuration_service.store.runtime_path,
                    native_runtime=runtime,
                )
        state = self.configuration_service.state()
        if state.status != "valid" or state.configuration is None:
            raise InstallerError(
                "MANAGED_CONFIGURATION_NOT_VALID",
                "A valid confirmed product configuration is required before start.",
                recovery_actions=["create_configuration_plan", "apply_configuration_plan"],
            )
        if state.revision != expected_revision:
            raise InstallerError(
                "CONFIGURATION_REVISION_CONFLICT",
                "Requested lifecycle revision is not the active configuration revision.",
                recovery_actions=["read_configuration_state", "retry_with_active_revision"],
            )
        configuration = state.configuration
        return RuntimeLaunchConfiguration(
            artifact_id=configuration.artifact_id,
            product_instance_id=configuration.product_instance_id,
            configuration_revision=configuration.configuration_revision,
            listen_host=configuration.listen_host,
            listen_port=configuration.listen_port,
            data_dir=configuration.data_dir,
            log_dir=configuration.log_dir,
            project_roots=(configuration.project_root,),
            config_path=self.configuration_service.store.path,
            legacy_configuration=configuration,
        )

    def _external_conflict(self) -> bool:
        if self.external_state_detector is None:
            return self._external_detected()
        target_port: int | None = None
        target_path: Path | None = None
        if self.native_configuration_service is not None:
            native = self.native_configuration_service.state()
            if native.runtime_config is not None:
                target_port = native.runtime_config.management_port
            target_path = self.native_configuration_service.store.runtime_path
        if target_port is None:
            legacy = self.configuration_service.state()
            if legacy.configuration is not None:
                target_port = legacy.configuration.listen_port
                target_path = self.configuration_service.store.path
        return self.external_state_detector.conflict(
            target_port=target_port,
            target_config_path=target_path,
        )

    def _release_runtime_leases(self, reason: str) -> None:
        if self.telegram_leases is not None:
            self.telegram_leases.release_runtime(["claude", "codex"], reason)

    def _runtime_credential_revisions(self) -> dict[str, int]:
        if self.telegram_identities is None:
            return {}
        revisions: dict[str, int] = {}
        for slot in ("claude", "codex"):
            identity = self.telegram_identities.get(slot)
            if identity is not None:
                revisions[slot] = identity.credential_revision
        return revisions

    def _ownership_context(self) -> str:
        management, lifecycle = self.configuration_service.owners()
        return canonical_digest(
            {
                "artifact_context": self.version_store.context_digest(),
                "management_owner": management.value,
                "lifecycle_owner": lifecycle.value,
                "external_detected": self.external_detector(),
            }
        )

    def _validate_ownership_context(self, plan: OwnershipPlan) -> None:
        if _is_expired(plan.expires_at):
            raise InstallerError(
                "OWNERSHIP_PLAN_EXPIRED",
                "Lifecycle ownership plan expired.",
                recovery_actions=["create_ownership_handoff_plan"],
            )
        if self._ownership_context() != plan.context_digest:
            raise InstallerError(
                "OWNERSHIP_PLAN_CONTEXT_CHANGED",
                "Artifact, owner, or external process state changed after planning.",
                retryable=True,
                recovery_actions=["create_ownership_handoff_plan"],
            )

    def _safe_environment(self, listen_port: int) -> dict[str, str]:
        allowed = {
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "LOCALAPPDATA",
            "APPDATA",
            "USERPROFILE",
            "HOMEDRIVE",
            "HOMEPATH",
            "LANG",
        }
        result = {name: value for name in allowed if (value := os.environ.get(name))}
        result.update(
            {
                "CC_CONNECT_MANAGED_INSTANCE": self.configuration_service.product_instance_id,
                "CC_CONNECT_MANAGED_LISTEN_HOST": "127.0.0.1",
                "CC_CONNECT_MANAGED_LISTEN_PORT": str(listen_port),
            }
        )
        return result

    def _rotate_log(self, path: Path, *, max_bytes: int = 1024 * 1024, backups: int = 3) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size >= max_bytes:
            oldest = path.with_suffix(path.suffix + f".{backups}")
            oldest.unlink(missing_ok=True)
            for index in range(backups - 1, 0, -1):
                source = path.with_suffix(path.suffix + f".{index}")
                if source.exists():
                    os.replace(source, path.with_suffix(path.suffix + f".{index + 1}"))
            os.replace(path, path.with_suffix(path.suffix + ".1"))
        return path

    def _fatal_log_detected(self) -> bool:
        path = self.layout.from_relative("state/logs/cc-connect-runtime.log")
        if not path.exists():
            return False
        try:
            tail = path.read_bytes()[-32_768:].decode("utf-8", errors="replace").casefold()
        except OSError:
            return False
        return any(marker in tail for marker in ("panic:", "fatal error:", "fatal:"))

    def _artifact_matches(self, identity: ProcessIdentity) -> bool:
        try:
            artifact = self.version_store.current()
        except InstallerError:
            return False
        return (
            artifact.artifact_id == identity.artifact_id
            and artifact.artifact_sha256 == identity.executable_sha256
            and os.path.normcase(str(artifact.executable))
            == os.path.normcase(identity.executable_path)
        )

    def _configuration_matches(self, identity: ProcessIdentity) -> bool:
        if self.native_configuration_service is not None:
            native = self.native_configuration_service.state()
            if native.status != "missing":
                return bool(
                    native.status == "valid"
                    and native.runtime_config is not None
                    and native.managed_state is not None
                    and native.revision == identity.configuration_revision
                    and native.runtime_config.management_port == identity.listen_port
                    and native.managed_state.artifact_id == identity.artifact_id
                    and native.managed_state.product_instance_id == identity.product_instance_id
                )
        state = self.configuration_service.state()
        return bool(
            state.status == "valid"
            and state.configuration is not None
            and state.revision == identity.configuration_revision
            and state.configuration.listen_port == identity.listen_port
            and state.configuration.listen_host == identity.listen_host
            and state.configuration.artifact_id == identity.artifact_id
        )

    def _stable_since(self, process_create_time: str) -> bool:
        try:
            return time.time() - float(process_create_time) >= self.stable_window_seconds
        except ValueError:
            return False

    def _poll_exit_code(self, pid: int) -> int | None:
        launched = self._launched.get(pid)
        if launched is not None:
            value = launched.poll()
            return int(value) if value is not None else None
        try:
            if self.process_factory(pid).is_running():
                return None
        except (OSError, psutil.Error):
            pass
        return None

    def _stop_verified_identity(self, identity: ProcessIdentity) -> None:
        try:
            self._terminate_verified_tree(identity)
        except InstallerError:
            raise
        finally:
            self._launched.pop(identity.pid, None)

    def _terminate_launch_handle(self, process: Any) -> None:
        """Stop only the just-created OS handle when identity capture cannot complete."""
        try:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=self.stop_timeout_seconds)
        except (OSError, psutil.Error, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=self.stop_timeout_seconds)
            except (OSError, psutil.Error, subprocess.TimeoutExpired):
                pass

    def _record_port(self, operation_id: str, evidence: PortOwnershipEvidence) -> None:
        with self.db.session() as session:
            session.add(
                PortOwnershipRecord(
                    ownership_id=new_id("port"),
                    component_id=COMPONENT_ID,
                    operation_id=operation_id,
                    listen_host=evidence.listen_host,
                    listen_port=evidence.listen_port,
                    owner_pid=evidence.owner_pid,
                    status=evidence.status,
                    evidence_json=json.dumps(redact_value(evidence.evidence), sort_keys=True),
                    created_at=utcnow(),
                )
            )

    def _phase(
        self, operation_id: str, phase: str, message: str, *, point_of_no_return: bool = False
    ) -> None:
        with self.db.session() as session:
            OperationStore(session).transition(
                operation_id,
                status=OperationStatus.RUNNING,
                phase=phase,
                message=message,
                point_of_no_return=point_of_no_return,
            )
            self._audit(session, operation_id, "lifecycle.progress", phase)

    def _complete_operation(
        self, operation_id: str, *, phase: str, message: str, result: dict[str, Any]
    ) -> None:
        with self.db.session() as session:
            OperationStore(session).transition(
                operation_id,
                status=OperationStatus.SUCCEEDED,
                phase=phase,
                message=message,
                result=result,
            )
            self._audit(session, operation_id, "lifecycle.completed", phase)

    def _fail_operation(self, operation_id: str, error: InstallerError, *, phase: str) -> None:
        canceled = error.code == "OPERATION_CANCELED"
        with self.db.session() as session:
            OperationStore(session).transition(
                operation_id,
                status=OperationStatus.CANCELED if canceled else OperationStatus.FAILED,
                phase="lifecycle_canceled" if canceled else phase,
                message=error.message,
                error=(
                    None
                    if canceled
                    else UserFacingError(
                        code=error.code,
                        message=error.message,
                        retryable=error.retryable,
                        recovery_actions=error.recovery_actions,
                    )
                ),
            )
            session.add(
                DiagnosticRecord(
                    diagnostic_id=new_id("diag"),
                    severity="error",
                    code=error.code,
                    summary="cc-connect lifecycle operation failed",
                    user_message=error.message,
                    suggested_actions_json=json.dumps(error.recovery_actions),
                    technical_details_json=json.dumps(redact_value(error.technical_details)),
                    redaction_applied=1,
                    created_at=utcnow(),
                    correlation_id="lifecycle",
                    operation_id=operation_id,
                    target_kind="component",
                    target_id=COMPONENT_ID,
                )
            )
            self._audit(session, operation_id, "lifecycle.failed", error.code)

    def _check_cancellation(self, operation_id: str) -> None:
        with self.db.session() as session:
            operation = OperationStore(session).get(operation_id)
        if operation is not None and operation.status == OperationStatus.CANCEL_REQUESTED:
            raise InstallerError(
                "OPERATION_CANCELED",
                "Lifecycle operation was canceled at a safe checkpoint.",
            )

    def _release_lease(self, operation_id: str) -> None:
        with self.db.session() as session:
            session.execute(
                delete(LifecycleLeaseRecord).where(
                    LifecycleLeaseRecord.operation_id == operation_id
                )
            )

    @staticmethod
    def _audit(session, operation_id: str, event_type: str, phase: str) -> None:
        sequence = session.scalar(
            select(func.coalesce(func.max(OperationEventRecord.sequence), 0)).where(
                OperationEventRecord.operation_id == operation_id
            )
        )
        now = utcnow()
        session.add(
            OperationEventRecord(
                operation_id=operation_id,
                sequence=int(sequence or 0) + 1,
                event_type=event_type,
                phase=phase,
                data_json="{}",
                created_at=now,
            )
        )
        lifecycle_sequence = session.scalar(
            select(func.coalesce(func.max(LifecycleEventRecord.sequence), 0)).where(
                LifecycleEventRecord.operation_id == operation_id
            )
        )
        session.add(
            LifecycleEventRecord(
                component_id=COMPONENT_ID,
                operation_id=operation_id,
                sequence=int(lifecycle_sequence or 0) + 1,
                event_type=event_type,
                phase=phase,
                data_json="{}",
                created_at=now,
            )
        )

    def _external_detected(self) -> bool:
        if ProcessIdentityInspector.external_candidate_detected(self.layout.root):
            return True
        candidate = shutil.which("cc-connect") or shutil.which("cc-connect.exe")
        if not candidate:
            return False
        try:
            return not Path(candidate).resolve().is_relative_to(self.layout.root.resolve(False))
        except OSError:
            return True

    @staticmethod
    def _management_owner(value: str) -> ManagementOwner:
        try:
            return ManagementOwner(value)
        except ValueError:
            return ManagementOwner.UNKNOWN

    @staticmethod
    def _lifecycle_owner(value: str) -> LifecycleOwner:
        try:
            return LifecycleOwner(value)
        except ValueError:
            return LifecycleOwner.UNKNOWN

    @staticmethod
    def _observed_state(value: str):
        allowed = {
            "unconfigured",
            "stopped",
            "starting",
            "running_partial",
            "crashed",
            "conflict",
            "unknown",
        }
        return value if value in allowed else "unknown"

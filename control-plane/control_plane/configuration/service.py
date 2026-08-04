from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from ..application.operation_store import OperationStore
from ..domain.models import Operation, OperationStatus, ResourceRef, UserFacingError
from ..installer.artifacts import InstallerError
from ..installer.paths import ComponentLayout, atomic_write_json
from ..installer.version_store import ManagedVersionStore
from ..lifecycle.port_ownership import PortOwnershipInspector
from ..operations import RecoveryDecision
from ..persistence.models import (
    ConfigurationBackupRecord,
    ConfigurationPlanRecord,
    ConfigurationRevisionRecord,
    DiagnosticRecord,
    IdempotencyRecord,
    ManagedProcessRecord,
    OperationEventRecord,
    PendingRepairRecord,
)
from ..persistence.session import Database
from ..security.redaction import redact_value
from .config_store import (
    CONFIG_RELATIVE_PATH,
    ConfigurationCommit,
    ConfigurationError,
    ConfigurationStore,
    configuration_digest,
)
from .credential import CredentialBackend, WindowsCredentialManagerBackend
from .models import (
    ConfigurationConfirmationRequest,
    ConfigurationPlan,
    ConfigurationPlanRequest,
    ConfigurationState,
    LifecycleOwner,
    ManagedConfiguration,
    ManagementOwner,
    SecretStatus,
)
from .templates import build_minimal_configuration

COMPONENT_ID = "cc-connect"


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def canonical_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _is_expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= utcnow()


class CcConnectConfigurationService:
    def __init__(
        self,
        database: Database,
        layout: ComponentLayout,
        *,
        version_store: ManagedVersionStore | None = None,
        port_inspector: PortOwnershipInspector | None = None,
        credential_backends: dict[str, CredentialBackend] | None = None,
        configuration_store: ConfigurationStore | None = None,
        external_conflict_detector: Callable[[], bool] | None = None,
    ) -> None:
        self.db = database
        self.layout = layout
        self.version_store = version_store or ManagedVersionStore(layout, database)
        self.port_inspector = port_inspector or PortOwnershipInspector()
        windows_backend = WindowsCredentialManagerBackend()
        self.credential_backends = credential_backends or {
            windows_backend.backend_id: windows_backend
        }
        self.store = configuration_store or ConfigurationStore(layout)
        self.external_conflict_detector = external_conflict_detector or self._external_detected
        self.product_instance_id = self._load_or_create_product_instance_id()

    def create_plan(self, request: ConfigurationPlanRequest) -> ConfigurationPlan:
        artifact = self.version_store.current()
        management_owner, lifecycle_owner = self.owners()
        if self.external_conflict_detector():
            raise ConfigurationError(
                "EXTERNAL_LIFECYCLE_CONFLICT",
                "An external cc-connect candidate is present; configuration ownership is unchanged.",
                recovery_actions=["stop_or_disambiguate_external_instance", "reprobe_ownership"],
            )
        if management_owner != ManagementOwner.PRODUCT:
            raise ConfigurationError(
                "MANAGEMENT_OWNER_NOT_PRODUCT",
                "Only the product owner may write the product-managed configuration.",
                recovery_actions=["create_ownership_handoff_plan"],
            )
        if lifecycle_owner != LifecycleOwner.PRODUCT:
            raise ConfigurationError(
                "LIFECYCLE_OWNER_NOT_PRODUCT",
                "Confirm a separate lifecycle ownership handoff before configuration planning.",
                recovery_actions=["create_ownership_handoff_plan"],
            )
        self._require_stopped_for_configuration()
        current_revision, current_digest, current_configuration = self._verified_current()
        rollback_configuration: ManagedConfiguration | None = None
        if request.rollback_to_revision is not None:
            rollback_configuration = self._load_revision(request.rollback_to_revision)
        if request.listen_port is not None:
            port = request.listen_port
        elif rollback_configuration is not None:
            port = rollback_configuration.listen_port
        elif current_configuration is not None:
            port = current_configuration.listen_port
        else:
            port = self.port_inspector.choose_available()
        if not self.port_inspector.is_available("127.0.0.1", port):
            raise ConfigurationError(
                "MANAGED_PORT_CONFLICT",
                "The planned loopback port is already occupied; no plan was created.",
                retryable=True,
                recovery_actions=["choose_another_managed_port"],
                technical_details={"listen_port": port},
            )
        now = utcnow()
        target_revision = current_revision + 1
        if rollback_configuration is None:
            configuration = build_minimal_configuration(
                artifact_id=artifact.artifact_id,
                product_instance_id=self.product_instance_id,
                listen_port=port,
                component_root=self.layout.root,
                revision=target_revision,
                created_at=(current_configuration.created_at if current_configuration else now),
                updated_at=now,
            )
        else:
            configuration = rollback_configuration.model_copy(
                update={
                    "artifact_id": artifact.artifact_id,
                    "product_instance_id": self.product_instance_id,
                    "listen_port": port,
                    "configuration_revision": target_revision,
                    "lifecycle_owner": LifecycleOwner.PRODUCT,
                    "management_owner": ManagementOwner.PRODUCT,
                    "updated_at": now,
                }
            )
        context_digest = self._context_digest(
            target_port=port,
            current_revision=current_revision,
            current_digest=current_digest,
        )
        plan = ConfigurationPlan(
            plan_id=new_id("config-plan"),
            plan_digest="sha256:" + "0" * 64,
            context_digest=context_digest,
            artifact_id=artifact.artifact_id,
            current_revision=current_revision,
            target_revision=target_revision,
            current_owner=management_owner,
            target_path=CONFIG_RELATIVE_PATH,
            expected_changes=[
                "write only the product-managed non-secret cc-connect TOML",
                f"advance configuration revision from {current_revision} to {target_revision}",
                f"reserve loopback port {port} in the confirmed plan",
            ],
            ports=[port],
            directories=[
                "state/config",
                "state/runtime-data",
                "state/logs",
                "state/project-placeholder",
            ],
            secret_refs=configuration.secret_refs,
            rollback_plan=[
                "restore exact pre-write bytes from the operation backup",
                "reparse and revalidate the restored configuration",
                "record pending_repair if restoration cannot be proven",
            ],
            rollback_to_revision=request.rollback_to_revision,
            created_at=now,
            expires_at=now + timedelta(seconds=request.expires_in_seconds),
        )
        digest_payload = {
            "plan": plan.model_dump(mode="json", exclude={"plan_digest"}),
            "target_configuration_digest": configuration_digest_from_model(configuration),
        }
        plan = plan.model_copy(update={"plan_digest": canonical_digest(digest_payload)})
        with self.db.session() as session:
            session.add(
                ConfigurationPlanRecord(
                    plan_id=plan.plan_id,
                    component_id=COMPONENT_ID,
                    artifact_id=plan.artifact_id,
                    plan_digest=plan.plan_digest,
                    context_digest=plan.context_digest,
                    plan_json=plan.model_dump_json(),
                    target_payload_json=configuration.model_dump_json(),
                    status="waiting_for_confirmation",
                    current_revision=current_revision,
                    target_revision=target_revision,
                    created_at=plan.created_at,
                    expires_at=plan.expires_at,
                    confirmed_at=None,
                    applied_at=None,
                )
            )
        return plan

    def get_plan(self, plan_id: str) -> ConfigurationPlan | None:
        with self.db.session() as session:
            record = session.get(ConfigurationPlanRecord, plan_id)
            return ConfigurationPlan.model_validate_json(record.plan_json) if record else None

    def confirm_plan(
        self,
        request: ConfigurationConfirmationRequest,
        *,
        idempotency_key: str,
        body: bytes,
    ) -> tuple[Operation, bool]:
        with self.db.session() as session:
            store = OperationStore(session)
            existing = session.get(IdempotencyRecord, idempotency_key)
            if existing is not None:
                return store.create(
                    kind="cc_connect_configuration_apply",
                    target_ref=ResourceRef(kind="component", id=COMPONENT_ID),
                    idempotency_key=idempotency_key,
                    method="POST",
                    resource="/api/v1/components/cc-connect/configuration:apply",
                    body=body,
                )
            record = session.get(ConfigurationPlanRecord, request.plan_id)
            if record is None:
                raise ConfigurationError(
                    "CONFIGURATION_PLAN_NOT_FOUND",
                    "Configuration plan was not found.",
                    recovery_actions=["create_configuration_plan"],
                )
            plan = ConfigurationPlan.model_validate_json(record.plan_json)
            self._validate_confirmation(plan, request)
            if record.status != "waiting_for_confirmation":
                raise ConfigurationError(
                    "CONFIGURATION_PLAN_ALREADY_USED",
                    "Configuration plan was already confirmed.",
                    recovery_actions=["create_configuration_plan"],
                )
            self._validate_plan_context(plan)
            operation, reused = store.create(
                kind="cc_connect_configuration_apply",
                target_ref=ResourceRef(kind="component", id=COMPONENT_ID),
                idempotency_key=idempotency_key,
                method="POST",
                resource="/api/v1/components/cc-connect/configuration:apply",
                body=body,
            )
            record.status = "confirmed"
            record.confirmed_at = utcnow()
            return operation, reused

    def execute_plan(self, operation_id: str, plan_id: str) -> dict[str, Any] | None:
        commit: ConfigurationCommit | None = None
        commit_recorded = False
        try:
            self._phase(operation_id, "configuration_preflight", "Revalidating confirmed plan")
            plan, target = self._load_execution_plan(plan_id)
            self._check_cancellation(operation_id)
            self._validate_plan_context(plan)
            _, expected_digest, _ = self._verified_current()
            self._phase(
                operation_id,
                "configuration_commit",
                "Atomically replacing product-managed configuration",
                point_of_no_return=True,
            )
            commit = self.store.commit(
                target,
                operation_id=operation_id,
                expected_current_digest=expected_digest,
            )
            self._record_commit(operation_id, plan, commit)
            commit_recorded = True
            result = {
                "component_id": COMPONENT_ID,
                "configuration_revision": plan.target_revision,
                "configuration_digest": commit.digest,
                "relative_path": CONFIG_RELATIVE_PATH,
                "listen_host": "127.0.0.1",
                "listen_port": target.listen_port,
                "telegram": "disabled",
                "secret_values_written": False,
                "rollback_from_revision": plan.rollback_to_revision,
            }
            self._complete(operation_id, result)
            return result
        except ConfigurationError as exc:
            if commit is not None and not commit_recorded:
                try:
                    self.store.restore_commit(commit)
                except ConfigurationError as rollback_error:
                    exc = ConfigurationError(
                        "CONFIGURATION_ROLLBACK_FAILED",
                        "Configuration metadata failed and pre-write bytes could not be restored.",
                        recovery_actions=["inspect_pending_repair"],
                        technical_details={
                            "apply_error": exc.code,
                            "rollback_error": rollback_error.code,
                        },
                    )
            self._configuration_failure(operation_id, plan_id, exc)
            return None
        except (InstallerError, SQLAlchemyError) as exc:
            if commit is not None:
                try:
                    self.store.restore_commit(commit)
                except ConfigurationError:
                    self._record_pending_repair(
                        operation_id,
                        "CONFIGURATION_DATABASE_COMMIT_ROLLBACK_FAILED",
                        {"error": type(exc).__name__},
                    )
            error = ConfigurationError(
                "CONFIGURATION_APPLY_FAILED",
                "Configuration apply did not complete and was rolled back where possible.",
                retryable=True,
                recovery_actions=["inspect_configuration_state", "retry_after_review"],
                technical_details={"error": type(exc).__name__},
            )
            self._configuration_failure(operation_id, plan_id, error)
            return None

    def state(self) -> ConfigurationState:
        management_owner, lifecycle_owner = self.owners()
        with self.db.session() as session:
            pending = session.scalar(
                select(func.count(PendingRepairRecord.repair_id)).where(
                    PendingRepairRecord.component_id == COMPONENT_ID,
                    PendingRepairRecord.status == "pending",
                )
            )
        if pending:
            return ConfigurationState(
                status="pending_repair",
                revision=self._latest_revision_number(),
                relative_path=CONFIG_RELATIVE_PATH,
                management_owner=management_owner,
                lifecycle_owner=lifecycle_owner,
                diagnostic_code="CONFIGURATION_PENDING_REPAIR",
            )
        try:
            revision, digest, configuration = self._verified_current()
        except ConfigurationError as exc:
            return ConfigurationState(
                status="drifted" if exc.code == "CONFIGURATION_MANUAL_DRIFT" else "invalid",
                revision=self._latest_revision_number(),
                digest=self.store.digest(),
                relative_path=CONFIG_RELATIVE_PATH,
                management_owner=management_owner,
                lifecycle_owner=lifecycle_owner,
                diagnostic_code=exc.code,
            )
        if configuration is None:
            return ConfigurationState(
                status="missing",
                revision=0,
                relative_path=CONFIG_RELATIVE_PATH,
                management_owner=management_owner,
                lifecycle_owner=lifecycle_owner,
            )
        statuses: dict[str, SecretStatus] = {}
        for reference in configuration.secret_refs:
            backend = self.credential_backends.get(reference.backend)
            statuses[reference.reference_id] = (
                backend.status(reference) if backend else SecretStatus.INACCESSIBLE
            )
        return ConfigurationState(
            status="valid",
            revision=revision,
            digest=digest,
            relative_path=CONFIG_RELATIVE_PATH,
            management_owner=management_owner,
            lifecycle_owner=lifecycle_owner,
            configuration=configuration,
            secret_status=statuses,
        )

    def validate_runtime_prerequisites(self, configuration: ManagedConfiguration) -> None:
        missing: list[str] = []
        inaccessible: list[str] = []
        for reference in configuration.secret_refs:
            if not reference.required:
                continue
            backend = self.credential_backends.get(reference.backend)
            status = backend.status(reference) if backend else SecretStatus.INACCESSIBLE
            if status == SecretStatus.MISSING:
                missing.append(reference.reference_id)
            elif status != SecretStatus.AVAILABLE:
                inaccessible.append(reference.reference_id)
        if missing:
            raise ConfigurationError(
                "SECRET_REFERENCE_MISSING",
                "A required SecretRef is missing; no credential value was read.",
                recovery_actions=["provide_credential_in_future_binding_slice"],
                technical_details={"reference_ids": missing},
            )
        if inaccessible:
            raise ConfigurationError(
                "SECRET_REFERENCE_INACCESSIBLE",
                "A required SecretRef cannot be verified; no credential value was read.",
                recovery_actions=["repair_credential_backend_access"],
                technical_details={"reference_ids": inaccessible},
            )

    def owners(self) -> tuple[ManagementOwner, LifecycleOwner]:
        with self.db.session() as session:
            record = session.get(ManagedProcessRecord, COMPONENT_ID)
        if record is None:
            try:
                self.version_store.current()
            except InstallerError:
                return ManagementOwner.UNMANAGED, LifecycleOwner.NONE
            return ManagementOwner.PRODUCT, LifecycleOwner.NONE
        try:
            return ManagementOwner(record.management_owner), LifecycleOwner(record.lifecycle_owner)
        except ValueError:
            return ManagementOwner.UNKNOWN, LifecycleOwner.UNKNOWN

    def recovery_probe(self, operation_id: str, payload: dict[str, Any]) -> RecoveryDecision:
        plan_id = str(payload.get("plan_id", ""))
        with self.db.session() as session:
            record = session.get(ConfigurationPlanRecord, plan_id)
            if record is None:
                return RecoveryDecision.fail(code="CONFIGURATION_PLAN_NOT_FOUND")
            revision = session.get(
                ConfigurationRevisionRecord, (COMPONENT_ID, record.target_revision)
            )
        if revision is not None and self.store.digest() == revision.configuration_digest:
            with self.db.session() as session:
                record = session.get(ConfigurationPlanRecord, plan_id)
                assert record is not None
                record.status = "applied"
                record.applied_at = record.applied_at or utcnow()
            return RecoveryDecision.complete(
                {
                    "component_id": COMPONENT_ID,
                    "configuration_revision": revision.revision,
                    "configuration_digest": revision.configuration_digest,
                    "recovered": True,
                }
            )
        if record.status == "confirmed":
            try:
                plan = ConfigurationPlan.model_validate_json(record.plan_json)
                self._validate_plan_context(plan)
                return RecoveryDecision.requeue()
            except ConfigurationError as exc:
                return RecoveryDecision.fail(
                    code=exc.code,
                    message=exc.message,
                    recovery_actions=exc.recovery_actions,
                )
        return RecoveryDecision.fail(code="CONFIGURATION_RECOVERY_STATE_CONFLICT")

    def _load_or_create_product_instance_id(self) -> str:
        self.layout.ensure()
        path = self.layout.from_relative("state/product-instance.json")
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
                value = str(payload["product_instance_id"])
                if value.startswith("instance-") and len(value) == 33:
                    return value
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                pass
            raise ConfigurationError(
                "PRODUCT_INSTANCE_ID_INVALID",
                "Product instance identity file is invalid.",
                recovery_actions=["inspect_product_state"],
            )
        value = f"instance-{uuid.uuid4().hex[:24]}"
        atomic_write_json(
            path,
            {
                "schema_version": "1.0",
                "product_instance_id": value,
                "created_at": utcnow().isoformat(),
            },
        )
        return value

    def _verified_current(
        self,
    ) -> tuple[int, str | None, ManagedConfiguration | None]:
        with self.db.session() as session:
            record = session.scalar(
                select(ConfigurationRevisionRecord)
                .where(ConfigurationRevisionRecord.component_id == COMPONENT_ID)
                .order_by(ConfigurationRevisionRecord.revision.desc())
                .limit(1)
            )
        disk_bytes = self.store.read_bytes()
        if record is None and disk_bytes is None:
            return 0, None, None
        if record is None or disk_bytes is None:
            raise ConfigurationError(
                "CONFIGURATION_MANUAL_DRIFT",
                "Configuration file and persistent revision history disagree.",
                recovery_actions=["create_configuration_rollback_plan", "inspect_product_state"],
            )
        digest = configuration_digest(disk_bytes)
        if digest != record.configuration_digest:
            raise ConfigurationError(
                "CONFIGURATION_MANUAL_DRIFT",
                "Product-managed configuration was modified outside the confirmed plan.",
                recovery_actions=["create_configuration_rollback_plan", "review_manual_change"],
            )
        configuration = self.store.read()
        assert configuration is not None
        if (
            configuration.configuration_revision != record.revision
            or configuration.artifact_id != record.artifact_id
            or configuration.product_instance_id != record.product_instance_id
        ):
            raise ConfigurationError(
                "CONFIGURATION_REVISION_RECORD_MISMATCH",
                "Configuration identity does not match its persistent revision record.",
                recovery_actions=["create_configuration_rollback_plan"],
            )
        return record.revision, digest, configuration

    def _context_digest(
        self,
        *,
        target_port: int,
        current_revision: int,
        current_digest: str | None,
    ) -> str:
        management_owner, lifecycle_owner = self.owners()
        payload = {
            "artifact_context": self.version_store.context_digest(),
            "current_revision": current_revision,
            "current_digest": current_digest,
            "management_owner": management_owner.value,
            "lifecycle_owner": lifecycle_owner.value,
            "target_port": target_port,
            "target_port_free": self.port_inspector.is_available("127.0.0.1", target_port),
        }
        return canonical_digest(payload)

    def _validate_plan_context(self, plan: ConfigurationPlan) -> None:
        if _is_expired(plan.expires_at):
            raise ConfigurationError(
                "CONFIGURATION_PLAN_EXPIRED",
                "Configuration plan expired before confirmation or execution.",
                recovery_actions=["create_configuration_plan"],
            )
        current_revision, current_digest, _ = self._verified_current()
        if current_revision != plan.current_revision:
            raise ConfigurationError(
                "CONFIGURATION_REVISION_CONFLICT",
                "Configuration revision changed after planning.",
                retryable=True,
                recovery_actions=["create_configuration_plan"],
            )
        current_context = self._context_digest(
            target_port=plan.ports[0],
            current_revision=current_revision,
            current_digest=current_digest,
        )
        if current_context != plan.context_digest:
            raise ConfigurationError(
                "CONFIGURATION_PLAN_CONTEXT_CHANGED",
                "Artifact, owner, configuration, or port state changed after planning.",
                retryable=True,
                recovery_actions=["create_configuration_plan"],
            )

    @staticmethod
    def _validate_confirmation(
        plan: ConfigurationPlan, request: ConfigurationConfirmationRequest
    ) -> None:
        if (
            request.plan_id != plan.plan_id
            or request.plan_digest != plan.plan_digest
            or request.current_revision != plan.current_revision
            or request.target_revision != plan.target_revision
            or not request.confirmation
        ):
            raise ConfigurationError(
                "CONFIGURATION_CONFIRMATION_MISMATCH",
                "Confirmation is not bound to the complete immutable configuration plan.",
                recovery_actions=["review_and_confirm_current_plan"],
            )

    def _load_execution_plan(self, plan_id: str) -> tuple[ConfigurationPlan, ManagedConfiguration]:
        with self.db.session() as session:
            record = session.get(ConfigurationPlanRecord, plan_id)
            if record is None:
                raise ConfigurationError(
                    "CONFIGURATION_PLAN_NOT_FOUND",
                    "Configuration plan was not found during execution.",
                    recovery_actions=["create_configuration_plan"],
                )
            if record.status != "confirmed":
                raise ConfigurationError(
                    "CONFIGURATION_PLAN_NOT_CONFIRMED",
                    "Configuration plan is not in the confirmed state.",
                    recovery_actions=["confirm_configuration_plan"],
                )
            plan = ConfigurationPlan.model_validate_json(record.plan_json)
            target = ManagedConfiguration.model_validate_json(record.target_payload_json)
        expected_digest = canonical_digest(
            {
                "plan": plan.model_dump(mode="json", exclude={"plan_digest"}),
                "target_configuration_digest": configuration_digest_from_model(target),
            }
        )
        if expected_digest != record.plan_digest or expected_digest != plan.plan_digest:
            raise ConfigurationError(
                "CONFIGURATION_PLAN_TAMPERED",
                "Persisted configuration plan or target payload was modified.",
                recovery_actions=["create_configuration_plan", "inspect_database_integrity"],
            )
        return plan, target

    def _record_commit(
        self, operation_id: str, plan: ConfigurationPlan, commit: ConfigurationCommit
    ) -> None:
        with self.db.session() as session:
            existing = session.get(
                ConfigurationRevisionRecord, (COMPONENT_ID, plan.target_revision)
            )
            if existing is not None:
                if existing.configuration_digest != commit.digest:
                    raise ConfigurationError(
                        "CONFIGURATION_REVISION_DUPLICATE_CONFLICT",
                        "Target revision already exists with a different digest.",
                        recovery_actions=["inspect_configuration_state"],
                    )
                return
            previous = session.get(
                ConfigurationRevisionRecord, (COMPONENT_ID, plan.current_revision)
            )
            if previous is not None:
                previous.status = "superseded"
            session.add(
                ConfigurationRevisionRecord(
                    component_id=COMPONENT_ID,
                    revision=plan.target_revision,
                    artifact_id=commit.configuration.artifact_id,
                    product_instance_id=commit.configuration.product_instance_id,
                    plan_id=plan.plan_id,
                    configuration_digest=commit.digest,
                    payload_json=commit.configuration.model_dump_json(),
                    relative_path=CONFIG_RELATIVE_PATH,
                    status="active",
                    created_at=utcnow(),
                )
            )
            if commit.backup_relative_path and commit.backup_digest:
                session.add(
                    ConfigurationBackupRecord(
                        backup_id=new_id("config-backup"),
                        component_id=COMPONENT_ID,
                        source_revision=plan.current_revision,
                        operation_id=operation_id,
                        relative_path=commit.backup_relative_path,
                        configuration_digest=commit.backup_digest,
                        status="available",
                        created_at=utcnow(),
                    )
                )
            plan_record = session.get(ConfigurationPlanRecord, plan.plan_id)
            assert plan_record is not None
            plan_record.status = "applied"
            plan_record.applied_at = utcnow()
            managed = session.get(ManagedProcessRecord, COMPONENT_ID)
            if managed is not None and managed.pid is None:
                managed.artifact_id = commit.configuration.artifact_id
                managed.configuration_revision = plan.target_revision
                managed.observed_state = "stopped"
                managed.updated_at = utcnow()

    def _load_revision(self, revision: int) -> ManagedConfiguration:
        with self.db.session() as session:
            record = session.get(ConfigurationRevisionRecord, (COMPONENT_ID, revision))
        if record is None:
            raise ConfigurationError(
                "CONFIGURATION_REVISION_NOT_FOUND",
                "Requested rollback revision does not exist.",
                recovery_actions=["list_configuration_revisions"],
            )
        return ManagedConfiguration.model_validate_json(record.payload_json)

    def _latest_revision_number(self) -> int:
        with self.db.session() as session:
            value = session.scalar(
                select(func.max(ConfigurationRevisionRecord.revision)).where(
                    ConfigurationRevisionRecord.component_id == COMPONENT_ID
                )
            )
        return int(value or 0)

    def _require_stopped_for_configuration(self) -> None:
        with self.db.session() as session:
            record = session.get(ManagedProcessRecord, COMPONENT_ID)
        if record is not None and record.observed_state in {"starting", "running_partial"}:
            raise ConfigurationError(
                "CONFIGURATION_CHANGE_REQUIRES_STOP",
                "Stop the product-managed process before changing its configuration.",
                recovery_actions=["stop_product_managed_cc_connect"],
            )

    def _check_cancellation(self, operation_id: str) -> None:
        with self.db.session() as session:
            operation = OperationStore(session).get(operation_id)
        if operation is not None and operation.status == OperationStatus.CANCEL_REQUESTED:
            raise ConfigurationError(
                "OPERATION_CANCELED",
                "Configuration apply was canceled before its atomic replacement point.",
                recovery_actions=["create_configuration_plan_if_needed"],
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
            self._audit(session, operation_id, "configuration.progress", phase)

    def _complete(self, operation_id: str, result: dict[str, Any]) -> None:
        with self.db.session() as session:
            OperationStore(session).transition(
                operation_id,
                status=OperationStatus.SUCCEEDED,
                phase="configuration_applied",
                message="Confirmed product-managed configuration was applied.",
                result=result,
            )
            self._audit(session, operation_id, "configuration.applied", "configuration_applied")

    def _configuration_failure(
        self, operation_id: str, plan_id: str, error: ConfigurationError
    ) -> None:
        now = utcnow()
        user_error = UserFacingError(
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            recovery_actions=error.recovery_actions,
        )
        with self.db.session() as session:
            operation = OperationStore(session).get(operation_id)
            canceled = error.code == "OPERATION_CANCELED"
            OperationStore(session).transition(
                operation_id,
                status=OperationStatus.CANCELED if canceled else OperationStatus.FAILED,
                phase="configuration_canceled" if canceled else "configuration_failed",
                message=error.message,
                error=None if canceled else user_error,
            )
            plan = session.get(ConfigurationPlanRecord, plan_id)
            if plan is not None and plan.status != "applied":
                plan.status = "canceled" if canceled else "failed"
            session.add(
                DiagnosticRecord(
                    diagnostic_id=new_id("diag"),
                    severity="error",
                    code=error.code,
                    summary="cc-connect configuration operation failed",
                    user_message=error.message,
                    suggested_actions_json=json.dumps(error.recovery_actions),
                    technical_details_json=json.dumps(redact_value(error.technical_details)),
                    redaction_applied=1,
                    created_at=now,
                    correlation_id="configuration",
                    operation_id=operation.operation_id if operation else operation_id,
                    target_kind="component",
                    target_id=COMPONENT_ID,
                )
            )
            self._audit(session, operation_id, "configuration.failed", error.code)
        if error.code == "CONFIGURATION_ROLLBACK_FAILED":
            self._record_pending_repair(operation_id, error.code, error.technical_details)

    def _record_pending_repair(
        self, operation_id: str, reason_code: str, details: dict[str, Any]
    ) -> None:
        now = utcnow()
        with self.db.session() as session:
            session.add(
                PendingRepairRecord(
                    repair_id=new_id("repair"),
                    component_id=COMPONENT_ID,
                    operation_id=operation_id,
                    reason_code=reason_code,
                    relative_path=CONFIG_RELATIVE_PATH,
                    details_json=json.dumps(redact_value(details), sort_keys=True),
                    status="pending",
                    created_at=now,
                    updated_at=now,
                )
            )

    @staticmethod
    def _audit(session, operation_id: str, event_type: str, phase: str) -> None:
        sequence = session.scalar(
            select(func.coalesce(func.max(OperationEventRecord.sequence), 0)).where(
                OperationEventRecord.operation_id == operation_id
            )
        )
        session.add(
            OperationEventRecord(
                operation_id=operation_id,
                sequence=int(sequence or 0) + 1,
                event_type=event_type,
                phase=phase,
                data_json="{}",
                created_at=utcnow(),
            )
        )

    def _external_detected(self) -> bool:
        candidate = shutil.which("cc-connect") or shutil.which("cc-connect.exe")
        if not candidate:
            return False
        try:
            return not Path(candidate).resolve().is_relative_to(self.layout.root.resolve(False))
        except OSError:
            return True


def configuration_digest_from_model(configuration: ManagedConfiguration) -> str:
    from .templates import render_managed_toml

    return configuration_digest(render_managed_toml(configuration))

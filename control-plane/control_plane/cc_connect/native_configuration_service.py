from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update

from ..application.operation_store import OperationStore
from ..configuration.models import LifecycleOwner, ManagementOwner
from ..configuration.service import CcConnectConfigurationService, canonical_digest
from ..credentials.models import (
    INTERNAL_CC_CONNECT_MANAGEMENT_REFERENCE,
    PUBLIC_CREDENTIAL_REFERENCES,
    CredentialStatus,
)
from ..credentials.service import CredentialService
from ..domain.models import Operation, ResourceRef
from ..installer.artifacts import InstallerError
from ..installer.paths import ComponentLayout
from ..installer.version_store import ManagedVersionStore
from ..operations import OperationExecutionError, RecoveryDecision
from ..persistence.models import (
    ComponentConfigRendererRecord,
    IdempotencyRecord,
    ManagedProcessRecord,
    NativeConfigurationBackupRecord,
    NativeConfigurationPlanRecord,
    NativeConfigurationRevisionRecord,
)
from ..persistence.session import Database
from ..telegram.binding_service import TelegramBindingService
from ..telegram.bot_identity import TelegramBotIdentityService
from ..telegram.models import BindingState
from .native_config_models import (
    ManagedCcConnectState,
    NativeConfigurationConfirmation,
    NativeConfigurationPlan,
    NativeConfigurationPlanRequest,
    NativeConfigurationState,
    NativeProject,
    NativeRuntimeConfig,
    NativeTelegramPlatform,
)
from .native_config_renderer import CcConnectNativeConfigRenderer
from .native_config_store import (
    MANAGED_RELATIVE_PATH,
    RUNTIME_RELATIVE_PATH,
    CcConnectNativeConfigStore,
    digest_bytes,
    managed_state_bytes,
)

COMPONENT_ID = "cc-connect"


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class CcConnectNativeConfigurationService:
    def __init__(
        self,
        database: Database,
        layout: ComponentLayout,
        credentials: CredentialService,
        identities: TelegramBotIdentityService,
        bindings: TelegramBindingService,
        ownership: CcConnectConfigurationService,
        *,
        version_store: ManagedVersionStore | None = None,
        renderer: CcConnectNativeConfigRenderer | None = None,
        agent_path_lookup=None,
    ) -> None:
        self.db = database
        self.layout = layout
        self.credentials = credentials
        self.identities = identities
        self.bindings = bindings
        self.ownership = ownership
        self.version_store = version_store or ManagedVersionStore(layout, database)
        self.renderer = renderer or CcConnectNativeConfigRenderer()
        self.agent_path_lookup = agent_path_lookup or shutil.which
        self.store = CcConnectNativeConfigStore(layout)
        self._record_renderer()

    def capability(self):
        return self.renderer.capability()

    def create_plan(self, request: NativeConfigurationPlanRequest) -> NativeConfigurationPlan:
        artifact = self.version_store.current()
        management, lifecycle = self.ownership.owners()
        if management != ManagementOwner.PRODUCT or lifecycle != LifecycleOwner.PRODUCT:
            raise InstallerError(
                "NATIVE_CONFIGURATION_OWNER_NOT_PRODUCT",
                "Native configuration requires explicit product management and lifecycle ownership.",
                recovery_actions=["create_ownership_handoff_plan"],
            )
        self.credentials.ensure_internal_runtime_credentials()
        now = utcnow()
        current_revision = self.latest_revision()
        target_revision = current_revision + 1
        if request.rollback_to_revision is not None:
            runtime, managed = self._load_revision(request.rollback_to_revision)
            managed = managed.model_copy(
                update={
                    "configuration_revision": target_revision,
                    "runtime_config_revision": target_revision,
                    "backup_references": [
                        *managed.backup_references,
                        f"native-revision:{request.rollback_to_revision}",
                    ],
                    "updated_at": now,
                }
            )
        else:
            runtime, managed = self._build_target(request, target_revision, now)
        self.renderer.validate(runtime)
        plan = NativeConfigurationPlan(
            plan_id=new_id("native-plan"),
            plan_digest="sha256:" + "0" * 64,
            context_digest=self._context_digest(request.binding_session_id),
            current_revision=current_revision,
            target_revision=target_revision,
            artifact_id=artifact.artifact_id,
            renderer_version=self.renderer.renderer_version,
            managed_state_relative_path=MANAGED_RELATIVE_PATH,
            runtime_config_relative_path=RUNTIME_RELATIVE_PATH,
            expected_changes=[
                "atomically write product management state separately from native cc-connect TOML",
                "render Claude Code and Codex Telegram projects for the locked upstream commit",
                "keep every secret as an environment placeholder and preserve the config while running",
                "record a recoverable backup before replacing an active revision",
            ],
            secret_environment_variables=[
                runtime.management_environment_variable,
                *[project.telegram.environment_variable for project in runtime.projects],
            ],
            rollback_to_revision=request.rollback_to_revision,
            created_at=now,
            expires_at=now + timedelta(seconds=request.expires_in_seconds),
        )
        digest = self._plan_digest(plan, runtime, managed)
        plan = plan.model_copy(update={"plan_digest": digest})
        with self.db.session() as session:
            session.add(
                NativeConfigurationPlanRecord(
                    plan_id=plan.plan_id,
                    component_id=COMPONENT_ID,
                    artifact_id=plan.artifact_id,
                    plan_digest=plan.plan_digest,
                    context_digest=plan.context_digest,
                    plan_json=plan.model_dump_json(),
                    runtime_payload_json=runtime.model_dump_json(),
                    managed_payload_json=managed.model_dump_json(),
                    status="waiting_for_confirmation",
                    current_revision=plan.current_revision,
                    target_revision=plan.target_revision,
                    created_at=plan.created_at,
                    expires_at=plan.expires_at,
                    confirmed_at=None,
                    applied_at=None,
                )
            )
        return plan

    def get_plan(self, plan_id: str) -> NativeConfigurationPlan | None:
        with self.db.session() as session:
            record = session.get(NativeConfigurationPlanRecord, plan_id)
            return NativeConfigurationPlan.model_validate_json(record.plan_json) if record else None

    def confirm_plan(
        self,
        request: NativeConfigurationConfirmation,
        *,
        idempotency_key: str,
        body: bytes,
    ) -> tuple[Operation, bool]:
        resource = "/api/v1/components/cc-connect/native-configuration:apply"
        with self.db.session() as session:
            operation_store = OperationStore(session)
            if session.get(IdempotencyRecord, idempotency_key) is not None:
                return operation_store.create(
                    kind="cc_connect_native_configuration_apply",
                    target_ref=ResourceRef(kind="component", id=COMPONENT_ID),
                    idempotency_key=idempotency_key,
                    method="POST",
                    resource=resource,
                    body=body,
                )
            record = session.get(NativeConfigurationPlanRecord, request.plan_id)
            if record is None:
                raise InstallerError(
                    "NATIVE_CONFIGURATION_PLAN_NOT_FOUND",
                    "Native configuration plan was not found.",
                    recovery_actions=["create_native_configuration_plan"],
                )
            plan = NativeConfigurationPlan.model_validate_json(record.plan_json)
            if (
                request.plan_id != plan.plan_id
                or request.plan_digest != plan.plan_digest
                or request.current_revision != plan.current_revision
                or request.target_revision != plan.target_revision
                or not request.confirmation
            ):
                raise InstallerError(
                    "NATIVE_CONFIGURATION_CONFIRMATION_MISMATCH",
                    "Confirmation is not bound to the immutable native configuration plan.",
                    recovery_actions=["review_native_configuration_plan"],
                )
            if record.status != "waiting_for_confirmation":
                raise InstallerError(
                    "NATIVE_CONFIGURATION_PLAN_ALREADY_USED",
                    "Native configuration plan was already confirmed or applied.",
                    recovery_actions=["create_native_configuration_plan"],
                )
            self._validate_plan_context(plan)
            operation, reused = operation_store.create(
                kind="cc_connect_native_configuration_apply",
                target_ref=ResourceRef(kind="component", id=COMPONENT_ID),
                idempotency_key=idempotency_key,
                method="POST",
                resource=resource,
                body=body,
            )
            record.status = "confirmed"
            record.confirmed_at = utcnow()
            return operation, reused

    def execute_plan(self, operation_id: str, plan_id: str) -> dict[str, Any]:
        try:
            plan, runtime, managed = self._load_confirmed_plan(plan_id)
            self._validate_plan_context(plan)
            self._require_stopped()
            self.validate_runtime_prerequisites(runtime, managed)
            runtime_data = self.renderer.render(runtime)
            commit = self.store.commit(
                operation_id=operation_id,
                runtime_data=runtime_data,
                managed_state=managed,
            )
            self._record_commit(operation_id, plan, runtime, managed, commit)
            return {
                "component_id": COMPONENT_ID,
                "configuration_revision": plan.target_revision,
                "runtime_config_digest": commit.runtime_digest,
                "managed_state_digest": commit.managed_digest,
                "renderer_version": self.renderer.renderer_version,
                "secrets_persisted": False,
            }
        except InstallerError as exc:
            with self.db.session() as session:
                record = session.get(NativeConfigurationPlanRecord, plan_id)
                if record is not None and record.status != "applied":
                    record.status = "failed"
            raise OperationExecutionError(
                exc.code,
                exc.message,
                retryable=exc.retryable,
                recovery_actions=exc.recovery_actions,
            ) from None

    def state(self) -> NativeConfigurationState:
        record = self._active_revision_record()
        runtime_data = self.store.read_runtime()
        managed_data = self.store.read_managed()
        if record is None:
            if runtime_data is None and managed_data is None:
                return NativeConfigurationState(status="missing", revision=0)
            return NativeConfigurationState(
                status="invalid",
                revision=0,
                diagnostic_code="NATIVE_CONFIGURATION_RECORD_MISSING",
            )
        try:
            runtime = NativeRuntimeConfig.model_validate_json(record.runtime_payload_json)
            managed = ManagedCcConnectState.model_validate_json(record.managed_payload_json)
            expected_runtime = self.renderer.render(runtime)
            expected_managed = managed_state_bytes(managed)
        except (ValueError, InstallerError):
            return NativeConfigurationState(
                status="invalid",
                revision=record.revision,
                diagnostic_code="NATIVE_CONFIGURATION_RECORD_INVALID",
            )
        if runtime_data is None or managed_data is None:
            return NativeConfigurationState(
                status="invalid",
                revision=record.revision,
                runtime_config=runtime,
                managed_state=managed,
                diagnostic_code="NATIVE_CONFIGURATION_FILE_MISSING",
            )
        runtime_digest = digest_bytes(runtime_data)
        managed_digest = digest_bytes(managed_data)
        if (
            runtime_data != expected_runtime
            or managed_data != expected_managed
            or runtime_digest != record.runtime_config_digest
            or managed_digest != record.managed_state_digest
        ):
            return NativeConfigurationState(
                status="drifted",
                revision=record.revision,
                runtime_config_digest=runtime_digest,
                managed_state_digest=managed_digest,
                runtime_config=runtime,
                managed_state=managed,
                diagnostic_code="NATIVE_CONFIGURATION_DRIFT",
            )
        try:
            current_artifact = self.version_store.current()
        except InstallerError:
            return NativeConfigurationState(
                status="invalid",
                revision=record.revision,
                runtime_config=runtime,
                managed_state=managed,
                diagnostic_code="NATIVE_CONFIGURATION_ARTIFACT_UNAVAILABLE",
            )
        if (
            record.artifact_id != managed.artifact_id
            or current_artifact.artifact_id != managed.artifact_id
            or runtime.renderer_version != managed.renderer_version
            or runtime.source_commit != managed.source_commit
        ):
            return NativeConfigurationState(
                status="invalid",
                revision=record.revision,
                runtime_config_digest=runtime_digest,
                managed_state_digest=managed_digest,
                runtime_config=runtime,
                managed_state=managed,
                diagnostic_code="NATIVE_CONFIGURATION_ARTIFACT_MISMATCH",
            )
        return NativeConfigurationState(
            status="valid",
            revision=record.revision,
            runtime_config_digest=runtime_digest,
            managed_state_digest=managed_digest,
            runtime_config=runtime,
            managed_state=managed,
        )

    def latest_revision(self) -> int:
        with self.db.session() as session:
            value = session.scalar(
                select(func.max(NativeConfigurationRevisionRecord.revision)).where(
                    NativeConfigurationRevisionRecord.component_id == COMPONENT_ID
                )
            )
        return int(value or 0)

    def runtime_for_start(
        self, expected_revision: int
    ) -> tuple[NativeRuntimeConfig, ManagedCcConnectState]:
        state = self.state()
        if state.status != "valid" or state.runtime_config is None or state.managed_state is None:
            raise InstallerError(
                "NATIVE_CONFIGURATION_NOT_VALID",
                "A valid native cc-connect configuration is required before start.",
                recovery_actions=["create_native_configuration_plan", "apply_native_configuration"],
            )
        if state.revision != expected_revision:
            raise InstallerError(
                "CONFIGURATION_REVISION_CONFLICT",
                "Requested lifecycle revision is not the active native configuration revision.",
                recovery_actions=["read_native_configuration_state"],
            )
        return state.runtime_config, state.managed_state

    def validate_runtime_prerequisites(
        self, runtime: NativeRuntimeConfig, managed: ManagedCcConnectState
    ) -> None:
        artifact = self.version_store.current()
        if artifact.artifact_id != managed.artifact_id:
            raise InstallerError(
                "NATIVE_CONFIGURATION_ARTIFACT_MISMATCH",
                "Native configuration is not bound to the active managed artifact.",
                recovery_actions=["create_native_configuration_plan"],
            )
        product_root = self.layout.root.resolve(strict=False)
        for path_value in (runtime.data_dir, runtime.log_dir):
            path = Path(path_value).resolve(strict=False)
            if not path.is_relative_to(product_root):
                raise InstallerError(
                    "NATIVE_RUNTIME_PATH_ESCAPE_BLOCKED",
                    "Native runtime data and log paths must remain product-managed.",
                    recovery_actions=["create_native_configuration_plan"],
                )
            path.mkdir(parents=True, exist_ok=True)
        for project in runtime.projects:
            workspace = Path(project.workspace_root)
            if not workspace.is_absolute() or not workspace.is_dir():
                raise InstallerError(
                    "NATIVE_WORKSPACE_NOT_AVAILABLE",
                    "A selected Claude Code or Codex workspace is not an existing directory.",
                    recovery_actions=["create_workspace", "create_native_configuration_plan"],
                )
        for reference_id in managed.credential_references:
            if self.credentials.get(reference_id).status != CredentialStatus.AVAILABLE:
                raise InstallerError(
                    "NATIVE_RUNTIME_CREDENTIAL_NOT_AVAILABLE",
                    "A required runtime credential is not available.",
                    recovery_actions=["put_or_replace_credential"],
                )
        for project in runtime.projects:
            command = "claude" if project.slot == "claude" else "codex"
            if self.agent_path_lookup(command) is None:
                raise InstallerError(
                    "NATIVE_AGENT_EXECUTABLE_NOT_AVAILABLE",
                    f"The required {command} executable is not available on the current user PATH.",
                    recovery_actions=["install_or_repair_agent", "rescan_components"],
                )
        identities = {
            identity.slot: identity for identity in self.identities.require_all_verified()
        }
        for project in runtime.projects:
            expected = identities[project.slot]
            recorded = managed.bot_identities.get(project.slot, {})
            if int(recorded.get("bot_id", 0)) != expected.bot_id:
                raise InstallerError(
                    "NATIVE_CONFIGURATION_BOT_IDENTITY_STALE",
                    "Native configuration bot identity no longer matches the verified credential.",
                    recovery_actions=["verify_bot_identity", "create_native_configuration_plan"],
                )

    def recovery_probe(self, _operation_id: str, payload: dict[str, Any]) -> RecoveryDecision:
        plan_id = str(payload.get("plan_id", ""))
        with self.db.session() as session:
            record = session.get(NativeConfigurationPlanRecord, plan_id)
        if record is None:
            return RecoveryDecision.fail(code="NATIVE_CONFIGURATION_RECOVERY_NOT_FOUND")
        if record.status == "applied":
            state = self.state()
            if state.status == "valid" and state.revision == record.target_revision:
                return RecoveryDecision.complete(state.model_dump(mode="json"))
        if record.status == "confirmed":
            try:
                self._validate_plan_context(
                    NativeConfigurationPlan.model_validate_json(record.plan_json)
                )
                return RecoveryDecision.requeue()
            except (InstallerError, ValueError):
                pass
        return RecoveryDecision.fail(code="NATIVE_CONFIGURATION_RECOVERY_REQUIRES_REVIEW")

    def _build_target(
        self,
        request: NativeConfigurationPlanRequest,
        target_revision: int,
        now: datetime,
    ) -> tuple[NativeRuntimeConfig, ManagedCcConnectState]:
        binding = self.bindings.get(request.binding_session_id)
        if (
            binding.state != BindingState.COMPLETED
            or binding.operator_user_id is None
            or binding.group_chat_id is None
            or binding.bound_private_count != 3
            or binding.bound_group_count != 3
        ):
            raise InstallerError(
                "TELEGRAM_BINDING_NOT_COMPLETE",
                "A completed three-bot binding is required for native configuration.",
                recovery_actions=["complete_three_bot_binding"],
            )
        identities = {
            identity.slot: identity for identity in self.identities.require_all_verified()
        }
        workspaces = {
            "claude": self._absolute_workspace(request.claude_workspace_root),
            "codex": self._absolute_workspace(request.codex_workspace_root),
        }
        projects: list[NativeProject] = []
        for slot in ("claude", "codex"):
            reference_id = PUBLIC_CREDENTIAL_REFERENCES[slot][0]
            env_name = f"AIAD_TELEGRAM_{slot.upper()}_BOT_TOKEN"
            projects.append(
                NativeProject(
                    project_id=f"{slot}-telegram",
                    display_name=f"{slot.title()} Telegram",
                    slot=slot,
                    agent_type="claudecode" if slot == "claude" else "codex",
                    workspace_root=workspaces[slot],
                    admin_from=str(binding.operator_user_id),
                    operator_user_id=binding.operator_user_id,
                    group_chat_id=binding.group_chat_id,
                    binding_revision=binding.revision,
                    telegram=NativeTelegramPlatform(
                        credential_reference_id=reference_id,
                        environment_variable=env_name,
                        allow_from=str(binding.operator_user_id),
                    ),
                )
            )
        runtime = NativeRuntimeConfig(
            data_dir=str(self.layout.from_relative("state/runtime-data").resolve(strict=False)),
            log_dir=str(self.layout.from_relative("state/logs").resolve(strict=False)),
            management_port=request.management_port,
            management_credential_reference_id=INTERNAL_CC_CONNECT_MANAGEMENT_REFERENCE,
            projects=projects,
        )
        artifact = self.version_store.current()
        bot_metadata: dict[str, dict[str, str | int | bool]] = {}
        for slot, identity in identities.items():
            bot_metadata[slot] = {
                "bot_id": identity.bot_id,
                "username": identity.username,
                "first_name": identity.first_name,
                "can_join_groups": identity.can_join_groups,
                "can_read_all_group_messages": identity.can_read_all_group_messages,
                "credential_revision": identity.credential_revision,
            }
        managed = ManagedCcConnectState(
            product_instance_id=self.ownership.product_instance_id,
            artifact_id=artifact.artifact_id,
            configuration_revision=target_revision,
            runtime_config_revision=target_revision,
            binding_session_id=binding.session_id,
            binding_revision=binding.revision,
            operator_user_id=binding.operator_user_id,
            group_chat_id=binding.group_chat_id,
            credential_references=[
                INTERNAL_CC_CONNECT_MANAGEMENT_REFERENCE,
                PUBLIC_CREDENTIAL_REFERENCES["claude"][0],
                PUBLIC_CREDENTIAL_REFERENCES["codex"][0],
            ],
            bot_identities=bot_metadata,
            audit_references=[f"binding:{binding.session_id}"],
            created_at=now,
            updated_at=now,
        )
        return runtime, managed

    @staticmethod
    def _absolute_workspace(value: str) -> str:
        path = Path(value)
        if not path.is_absolute():
            raise InstallerError(
                "NATIVE_WORKSPACE_PATH_NOT_ABSOLUTE",
                "Claude Code and Codex workspace paths must be absolute.",
                recovery_actions=["select_workspace"],
            )
        return str(path.resolve(strict=False))

    def _load_confirmed_plan(
        self, plan_id: str
    ) -> tuple[NativeConfigurationPlan, NativeRuntimeConfig, ManagedCcConnectState]:
        with self.db.session() as session:
            record = session.get(NativeConfigurationPlanRecord, plan_id)
            if record is None or record.status != "confirmed":
                raise InstallerError(
                    "NATIVE_CONFIGURATION_PLAN_NOT_CONFIRMED",
                    "Native configuration plan is missing or not confirmed.",
                    recovery_actions=["create_native_configuration_plan"],
                )
            plan = NativeConfigurationPlan.model_validate_json(record.plan_json)
            runtime = NativeRuntimeConfig.model_validate_json(record.runtime_payload_json)
            managed = ManagedCcConnectState.model_validate_json(record.managed_payload_json)
        if self._plan_digest(plan, runtime, managed) != plan.plan_digest:
            raise InstallerError(
                "NATIVE_CONFIGURATION_PLAN_TAMPERED",
                "Persisted native configuration plan or target payload was modified.",
                recovery_actions=["create_native_configuration_plan", "inspect_database_integrity"],
            )
        return plan, runtime, managed

    def _load_revision(self, revision: int) -> tuple[NativeRuntimeConfig, ManagedCcConnectState]:
        with self.db.session() as session:
            record = session.get(NativeConfigurationRevisionRecord, (COMPONENT_ID, revision))
        if record is None:
            raise InstallerError(
                "NATIVE_CONFIGURATION_REVISION_NOT_FOUND",
                "Requested native configuration rollback revision does not exist.",
                recovery_actions=["read_native_configuration_state"],
            )
        return (
            NativeRuntimeConfig.model_validate_json(record.runtime_payload_json),
            ManagedCcConnectState.model_validate_json(record.managed_payload_json),
        )

    def _record_commit(self, operation_id, plan, runtime, managed, commit) -> None:
        with self.db.session() as session:
            previous = session.scalar(
                select(NativeConfigurationRevisionRecord).where(
                    NativeConfigurationRevisionRecord.component_id == COMPONENT_ID,
                    NativeConfigurationRevisionRecord.status == "active",
                )
            )
            if previous is not None:
                previous.status = "superseded"
            session.add(
                NativeConfigurationRevisionRecord(
                    component_id=COMPONENT_ID,
                    revision=plan.target_revision,
                    artifact_id=plan.artifact_id,
                    plan_id=plan.plan_id,
                    runtime_payload_json=runtime.model_dump_json(),
                    managed_payload_json=managed.model_dump_json(),
                    runtime_config_digest=commit.runtime_digest,
                    managed_state_digest=commit.managed_digest,
                    runtime_config_relative_path=RUNTIME_RELATIVE_PATH,
                    managed_state_relative_path=MANAGED_RELATIVE_PATH,
                    status="active",
                    created_at=utcnow(),
                )
            )
            if commit.backup_runtime_relative_path or commit.backup_managed_relative_path:
                session.add(
                    NativeConfigurationBackupRecord(
                        backup_id=new_id("native-backup"),
                        component_id=COMPONENT_ID,
                        source_revision=plan.current_revision,
                        operation_id=operation_id,
                        runtime_relative_path=commit.backup_runtime_relative_path,
                        managed_relative_path=commit.backup_managed_relative_path,
                        runtime_digest=commit.backup_runtime_digest,
                        managed_digest=commit.backup_managed_digest,
                        status="available",
                        created_at=utcnow(),
                    )
                )
            plan_record = session.get(NativeConfigurationPlanRecord, plan.plan_id)
            assert plan_record is not None
            plan_record.status = "applied"
            plan_record.applied_at = utcnow()
            managed_process = session.get(ManagedProcessRecord, COMPONENT_ID)
            if managed_process is not None:
                if managed_process.pid is not None:
                    raise InstallerError(
                        "NATIVE_CONFIGURATION_CHANGE_REQUIRES_STOP",
                        "Native configuration cannot be committed while a managed PID is recorded.",
                        recovery_actions=["stop_product_managed_cc_connect"],
                    )
                managed_process.product_instance_id = managed.product_instance_id
                managed_process.artifact_id = managed.artifact_id
                managed_process.configuration_revision = plan.target_revision
                managed_process.observed_state = "stopped"
                managed_process.updated_at = utcnow()

    def _active_revision_record(self) -> NativeConfigurationRevisionRecord | None:
        with self.db.session() as session:
            return session.scalar(
                select(NativeConfigurationRevisionRecord)
                .where(
                    NativeConfigurationRevisionRecord.component_id == COMPONENT_ID,
                    NativeConfigurationRevisionRecord.status == "active",
                )
                .order_by(NativeConfigurationRevisionRecord.revision.desc())
            )

    def _context_digest(self, binding_session_id: str) -> str:
        binding = self.bindings.get(binding_session_id)
        management, lifecycle = self.ownership.owners()
        runtime = self.store.read_runtime()
        managed = self.store.read_managed()
        return canonical_digest(
            {
                "artifact_context": self.version_store.context_digest(),
                "binding_session_id": binding.session_id,
                "binding_state": binding.state.value,
                "binding_revision": binding.revision,
                "current_revision": self.latest_revision(),
                "management_owner": management.value,
                "lifecycle_owner": lifecycle.value,
                "runtime_digest": digest_bytes(runtime) if runtime is not None else None,
                "managed_digest": digest_bytes(managed) if managed is not None else None,
            }
        )

    def _validate_plan_context(self, plan: NativeConfigurationPlan) -> None:
        if _aware(plan.expires_at) <= utcnow():
            raise InstallerError(
                "NATIVE_CONFIGURATION_PLAN_EXPIRED",
                "Native configuration plan expired.",
                recovery_actions=["create_native_configuration_plan"],
            )
        with self.db.session() as session:
            record = session.get(NativeConfigurationPlanRecord, plan.plan_id)
        if record is None:
            raise InstallerError(
                "NATIVE_CONFIGURATION_PLAN_NOT_FOUND",
                "Native configuration plan was not found.",
                recovery_actions=["create_native_configuration_plan"],
            )
        managed = ManagedCcConnectState.model_validate_json(record.managed_payload_json)
        if self._context_digest(managed.binding_session_id) != plan.context_digest:
            raise InstallerError(
                "NATIVE_CONFIGURATION_PLAN_CONTEXT_CHANGED",
                "Artifact, binding, ownership, or on-disk native configuration changed after planning.",
                retryable=True,
                recovery_actions=["create_native_configuration_plan"],
            )

    def _require_stopped(self) -> None:
        with self.db.session() as session:
            record = session.get(ManagedProcessRecord, COMPONENT_ID)
        if record is not None and (
            record.pid is not None or record.observed_state in {"starting", "running_partial"}
        ):
            raise InstallerError(
                "NATIVE_CONFIGURATION_CHANGE_REQUIRES_STOP",
                "Stop the product-managed process before changing native configuration.",
                recovery_actions=["stop_product_managed_cc_connect"],
            )

    @staticmethod
    def _plan_digest(
        plan: NativeConfigurationPlan,
        runtime: NativeRuntimeConfig,
        managed: ManagedCcConnectState,
    ) -> str:
        return canonical_digest(
            {
                "plan": plan.model_dump(mode="json", exclude={"plan_digest"}),
                "runtime": runtime.model_dump(mode="json"),
                "managed": managed.model_dump(mode="json"),
            }
        )

    def _record_renderer(self) -> None:
        capability = self.renderer.capability()
        renderer_id = f"cc-connect:{self.renderer.renderer_version}"
        with self.db.session() as session:
            session.execute(
                update(ComponentConfigRendererRecord)
                .where(
                    ComponentConfigRendererRecord.component_id == COMPONENT_ID,
                    ComponentConfigRendererRecord.renderer_id != renderer_id,
                )
                .values(active=0)
            )
            session.merge(
                ComponentConfigRendererRecord(
                    renderer_id=renderer_id,
                    component_id=COMPONENT_ID,
                    renderer_version=self.renderer.renderer_version,
                    source_commit=self.renderer.source_commit,
                    capability_json=json.dumps(capability.model_dump(mode="json"), sort_keys=True),
                    active=1,
                    updated_at=utcnow(),
                )
            )

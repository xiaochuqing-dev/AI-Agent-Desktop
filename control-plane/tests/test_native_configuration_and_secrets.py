from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from control_plane.cc_connect.native_config_models import (
    NativeConfigurationConfirmation,
    NativeConfigurationPlanRequest,
    NativeProject,
    NativeRuntimeConfig,
    NativeTelegramPlatform,
)
from control_plane.cc_connect.native_config_renderer import CcConnectNativeConfigRenderer
from control_plane.cc_connect.native_configuration_service import (
    CcConnectNativeConfigurationService,
)
from control_plane.cc_connect.runtime_secret_injector import RuntimeSecretInjector
from control_plane.credentials.models import INTERNAL_CC_CONNECT_MANAGEMENT_REFERENCE
from control_plane.hermes.config_renderer import HermesConfigurationPlanner
from control_plane.hermes.models import HermesConfigurationPlanRequest
from control_plane.installer.models import ArtifactManifest, RestoreRequest
from control_plane.lifecycle.managed_process import ManagedProcessService
from control_plane.operations import OperationExecutionError
from control_plane.persistence.models import (
    ComponentConfigRendererRecord,
    ComponentVersionRecord,
    ManagedProcessRecord,
    NativeConfigurationBackupRecord,
    NativeConfigurationRevisionRecord,
    RuntimeSecretInjectionAuditRecord,
)
from control_plane.telegram.models import UpdateOwner

from .telegram_helpers import build_telegram_services, complete_binding
from .test_installer_service import confirm_plan, load_operation, make_plan
from .test_lifecycle_service import FakeIdentityInspector, FakeLauncher, FakePortInspector, execute


def apply_native(service, request):
    plan = service.create_plan(request)
    confirmation = NativeConfigurationConfirmation(
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        current_revision=plan.current_revision,
        target_revision=plan.target_revision,
        confirmation=True,
    )
    operation, _ = service.confirm_plan(
        confirmation,
        idempotency_key=f"native-config-{uuid.uuid4().hex}",
        body=confirmation.model_dump_json().encode(),
    )
    result = service.execute_plan(operation.operation_id, plan.plan_id)
    return plan, result


def prepared_native_environment(environment, tmp_path):
    database = environment["database"]
    backend, credentials, client, identities, leases, bindings = build_telegram_services(database)
    created, completed = complete_binding(database, client, bindings)
    assert completed.state.value == "completed"
    service = CcConnectNativeConfigurationService(
        database,
        environment["installer"].layout,
        credentials,
        identities,
        bindings,
        environment["configuration"],
        version_store=environment["version_store"],
        agent_path_lookup=lambda command: f"C:\\synthetic\\{command}.cmd",
    )
    claude_workspace = tmp_path / "Claude 项目 (受管测试)"
    codex_workspace = tmp_path / "Codex 项目 (受管测试)"
    claude_workspace.mkdir()
    codex_workspace.mkdir()
    request = NativeConfigurationPlanRequest(
        binding_session_id=created.session_id,
        claude_workspace_root=str(claude_workspace.resolve()),
        codex_workspace_root=str(codex_workspace.resolve()),
        management_port=59020,
    )
    return {
        "backend": backend,
        "credentials": credentials,
        "client": client,
        "identities": identities,
        "leases": leases,
        "bindings": bindings,
        "binding": created,
        "service": service,
        "request": request,
    }


def test_locked_renderer_matches_legacy_and_current_native_toml_fixtures():
    config = NativeRuntimeConfig(
        data_dir=r"C:\AIAD\cc-connect",
        log_dir=r"C:\AIAD\logs",
        management_port=59020,
        management_credential_reference_id=INTERNAL_CC_CONNECT_MANAGEMENT_REFERENCE,
        projects=[
            NativeProject(
                project_id="claude-private",
                display_name="Claude private",
                slot="claude",
                agent_type="claudecode",
                workspace_root=r"C:\AIAD\workspaces\claude",
                admin_from="123456789",
                operator_user_id=123456789,
                group_chat_id=-100123456789,
                binding_revision=1,
                telegram=NativeTelegramPlatform(
                    credential_reference_id="credential://telegram/claude",
                    environment_variable="AIAD_TELEGRAM_CLAUDE_BOT_TOKEN",
                    allow_from="123456789",
                ),
            ),
            NativeProject(
                project_id="codex-group",
                display_name="Codex group",
                slot="codex",
                agent_type="codex",
                workspace_root=r"C:\AIAD\workspaces\codex",
                admin_from="123456789",
                operator_user_id=123456789,
                group_chat_id=-100123456789,
                binding_revision=1,
                telegram=NativeTelegramPlatform(
                    credential_reference_id="credential://telegram/codex",
                    environment_variable="AIAD_TELEGRAM_CODEX_BOT_TOKEN",
                    allow_from="123456789",
                ),
            ),
        ],
    )
    rendered = CcConnectNativeConfigRenderer().render(config)
    fixture_root = Path(__file__).resolve().parents[2] / "integrations" / "cc-connect" / "fixtures"
    assert rendered == (fixture_root / "native-v1-legacy.toml").read_bytes()
    assert rendered == (fixture_root / "native-v2-current.toml").read_bytes()


def test_native_config_separates_product_state_and_locked_upstream_toml(
    managed_runtime_environment, tmp_path
):
    prepared = prepared_native_environment(managed_runtime_environment, tmp_path)
    service = prepared["service"]
    plan, result = apply_native(service, prepared["request"])
    state = service.state()

    assert state.status == "valid"
    assert state.revision == 1
    assert result["secrets_persisted"] is False
    runtime_text = service.store.runtime_path.read_text(encoding="utf-8")
    managed_text = service.store.managed_path.read_text(encoding="utf-8")
    assert "${AIAD_TELEGRAM_CLAUDE_BOT_TOKEN}" in runtime_text
    assert "${AIAD_TELEGRAM_CODEX_BOT_TOKEN}" in runtime_text
    assert "${AIAD_CC_CONNECT_MANAGEMENT_TOKEN}" in runtime_text
    assert 'type = "claudecode"' in runtime_text
    assert 'type = "codex"' in runtime_text
    assert "management_owner" not in runtime_text
    assert "group_chat_id" not in runtime_text
    assert "credential_reference_id" not in runtime_text
    assert '"management_owner": "product"' in managed_text
    assert '"native_group_chat_filter_status": "unsupported"' in managed_text
    database_bytes = Path(managed_runtime_environment["settings"].db_path).read_bytes()
    for secret in (
        "100001:synthetic-hermes-token",
        "100002:synthetic-claude-token",
        "100003:synthetic-codex-token",
    ):
        assert secret not in runtime_text
        assert secret not in managed_text
        assert secret.encode() not in database_bytes
    assert plan.renderer_version == "cc-connect-17c6106-native-v2"
    assert state.runtime_config.source_commit == "17c61062c2f9ce9bcdd45a2082e491f9743a2770"
    assert state.managed_state.source_commit == "17c61062c2f9ce9bcdd45a2082e491f9743a2770"

    legacy_runtime = state.runtime_config.model_copy(
        update={
            "renderer_version": "cc-connect-fc315d2-native-v1",
            "source_commit": "fc315d213b49d62e9d90ea4a510189d4115e636f",
        }
    )
    legacy_managed = state.managed_state.model_copy(
        update={
            "renderer_version": "cc-connect-fc315d2-native-v1",
            "source_commit": "fc315d213b49d62e9d90ea4a510189d4115e636f",
        }
    )
    assert CcConnectNativeConfigRenderer().render(legacy_runtime) == runtime_text.encode()
    assert legacy_managed.renderer_version == "cc-connect-fc315d2-native-v1"

    mismatched = state.runtime_config.model_dump()
    mismatched["renderer_version"] = "cc-connect-fc315d2-native-v1"
    with pytest.raises(ValidationError, match="renderer version and locked cc-connect source"):
        NativeRuntimeConfig.model_validate(mismatched)


def test_native_config_revision_backup_drift_and_rollback(managed_runtime_environment, tmp_path):
    prepared = prepared_native_environment(managed_runtime_environment, tmp_path)
    service = prepared["service"]
    first, _ = apply_native(service, prepared["request"])
    second_request = prepared["request"].model_copy(update={"management_port": 59021})
    second, _ = apply_native(service, second_request)
    assert (first.target_revision, second.target_revision) == (1, 2)
    assert service.state().runtime_config.management_port == 59021

    rollback_request = prepared["request"].model_copy(
        update={"rollback_to_revision": 1, "management_port": 59022}
    )
    rollback, _ = apply_native(service, rollback_request)
    assert rollback.target_revision == 3
    assert service.state().runtime_config.management_port == 59020
    with managed_runtime_environment["database"].session() as session:
        backups = list(session.scalars(select(NativeConfigurationBackupRecord)))
    assert len(backups) == 2

    service.store.runtime_path.write_text("drift = true\n", encoding="utf-8")
    drifted = service.state()
    assert drifted.status == "drifted"
    assert drifted.diagnostic_code == "NATIVE_CONFIGURATION_DRIFT"


def _add_v141_managed_version(environment) -> ArtifactManifest:
    installer = environment["installer"]
    database = environment["database"]
    target_manifest = environment["manifest"]
    artifact = (
        Path(environment["settings"].trusted_artifact_dir) / target_manifest.artifact_filename
    ).read_bytes()
    payload = target_manifest.model_dump(mode="json")
    payload.update(
        {
            "artifact_id": "cc-connect-v1.4.1-patchset0.1-fc315d2-windows-amd64",
            "version": "v1.4.1-patchset0.1-fc315d2",
            "upstream_version": "1.4.1",
            "patchset_version": "0.1",
            "source_commit": "fc315d213b49d62e9d90ea4a510189d4115e636f",
        }
    )
    legacy = ArtifactManifest.model_validate(payload)
    version_dir = installer.layout.version_dir(legacy.artifact_id)
    version_dir.mkdir(parents=True)
    (version_dir / legacy.artifact_filename).write_bytes(artifact)
    (version_dir / "cc-connect-artifact-manifest.json").write_text(
        json.dumps(legacy.model_dump(mode="json"), sort_keys=True), encoding="utf-8"
    )
    (version_dir / "install-record.json").write_text(
        json.dumps(
            {
                "component_id": "cc-connect",
                "artifact_id": legacy.artifact_id,
                "artifact_sha256": legacy.artifact_sha256,
                "operation_id": "legacy-v141-fixture",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    with database.session() as session:
        session.add(
            ComponentVersionRecord(
                artifact_id=legacy.artifact_id,
                component_id="cc-connect",
                version=legacy.version,
                relative_path=f"versions/{legacy.artifact_id}",
                artifact_sha256=legacy.artifact_sha256,
                artifact_size=legacy.artifact_size,
                status="installed",
                installed_at=datetime.now(UTC),
                removed_at=None,
            )
        )
    return legacy


def test_v141_to_v150_native_upgrade_and_controlled_rollback(managed_runtime_environment, tmp_path):
    installer = managed_runtime_environment["installer"]
    database = managed_runtime_environment["database"]
    target_manifest = managed_runtime_environment["manifest"]
    legacy = _add_v141_managed_version(managed_runtime_environment)
    current = installer.layout.read_current()
    assert current is not None
    current.update(
        {
            "artifact_id": legacy.artifact_id,
            "version": legacy.version,
            "artifact_sha256": legacy.artifact_sha256,
            "previous_artifact_id": None,
            "operation_id": "legacy-v141-fixture",
            "revision": "legacy-v141-current",
        }
    )
    installer.layout.write_current(current)
    with database.session() as session:
        session.add(
            ComponentConfigRendererRecord(
                renderer_id="cc-connect:cc-connect-fc315d2-native-v1",
                component_id="cc-connect",
                renderer_version="cc-connect-fc315d2-native-v1",
                source_commit="fc315d213b49d62e9d90ea4a510189d4115e636f",
                capability_json="{}",
                active=1,
                updated_at=datetime.now(UTC),
            )
        )

    prepared = prepared_native_environment(managed_runtime_environment, tmp_path)
    native = prepared["service"]
    first_plan, _ = apply_native(native, prepared["request"])
    first_runtime = native.store.runtime_path.read_bytes()
    assert native.state().managed_state.artifact_id == legacy.artifact_id

    install_plan = make_plan(installer, target_manifest)
    install_operation, _, _, _ = confirm_plan(installer, install_plan, "native-upgrade-v150-target")
    installer.execute_install(install_operation.operation_id, install_plan.plan_id, "test")
    completed = load_operation(database, install_operation.operation_id)
    assert completed and completed.status.value == "succeeded"
    assert installer.layout.read_current()["artifact_id"] == target_manifest.artifact_id
    transitional = native.state()
    assert transitional.status == "invalid"
    assert transitional.diagnostic_code == "NATIVE_CONFIGURATION_ARTIFACT_MISMATCH"

    second_plan, _ = apply_native(native, prepared["request"])
    upgraded = native.state()
    assert (first_plan.target_revision, second_plan.target_revision) == (1, 2)
    assert upgraded.status == "valid"
    assert upgraded.managed_state.artifact_id == target_manifest.artifact_id
    assert upgraded.managed_state.renderer_version == "cc-connect-17c6106-native-v2"
    assert native.store.runtime_path.read_bytes() == first_runtime
    with database.session() as session:
        active_revision = session.scalar(
            select(NativeConfigurationRevisionRecord).where(
                NativeConfigurationRevisionRecord.component_id == "cc-connect",
                NativeConfigurationRevisionRecord.status == "active",
            )
        )
        managed_process = session.get(ManagedProcessRecord, "cc-connect")
        renderers = {
            item.renderer_version: item.active
            for item in session.scalars(select(ComponentConfigRendererRecord))
        }
    assert active_revision.artifact_id == target_manifest.artifact_id
    assert managed_process.artifact_id == target_manifest.artifact_id
    assert managed_process.configuration_revision == 2
    assert renderers["cc-connect-fc315d2-native-v1"] == 0
    assert renderers["cc-connect-17c6106-native-v2"] == 1

    restore_request = RestoreRequest(confirm=True)
    restore_operation, _ = installer.create_restore_operation(
        restore_request,
        idempotency_key="native-upgrade-restore-v141",
        body=restore_request.model_dump_json().encode(),
    )
    installer.execute_restore(restore_operation.operation_id, restore_request, "test")
    assert installer.layout.read_current()["artifact_id"] == legacy.artifact_id
    assert native.state().diagnostic_code == "NATIVE_CONFIGURATION_ARTIFACT_MISMATCH"

    rollback_request = prepared["request"].model_copy(update={"rollback_to_revision": 1})
    rollback_plan, _ = apply_native(native, rollback_request)
    rolled_back = native.state()
    assert rollback_plan.target_revision == 3
    assert rolled_back.status == "valid"
    assert rolled_back.managed_state.artifact_id == legacy.artifact_id
    assert native.store.runtime_path.read_bytes() == first_runtime
    assert installer.layout.version_dir(target_manifest.artifact_id).is_dir()
    assert installer.layout.version_dir(legacy.artifact_id).is_dir()
    with database.session() as session:
        active_revision = session.scalar(
            select(NativeConfigurationRevisionRecord).where(
                NativeConfigurationRevisionRecord.component_id == "cc-connect",
                NativeConfigurationRevisionRecord.status == "active",
            )
        )
        managed_process = session.get(ManagedProcessRecord, "cc-connect")
    assert active_revision.artifact_id == legacy.artifact_id
    assert managed_process.artifact_id == legacy.artifact_id
    assert managed_process.configuration_revision == 3


def test_native_apply_rejects_missing_workspace_and_empty_projects(
    managed_runtime_environment, tmp_path
):
    prepared = prepared_native_environment(managed_runtime_environment, tmp_path)
    missing = tmp_path / "missing workspace"
    request = prepared["request"].model_copy(
        update={"claude_workspace_root": str(missing.resolve())}
    )
    plan = prepared["service"].create_plan(request)
    confirmation = NativeConfigurationConfirmation(
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        current_revision=plan.current_revision,
        target_revision=plan.target_revision,
        confirmation=True,
    )
    operation, _ = prepared["service"].confirm_plan(
        confirmation,
        idempotency_key=f"native-config-{uuid.uuid4().hex}",
        body=confirmation.model_dump_json().encode(),
    )
    with pytest.raises(OperationExecutionError) as caught:
        prepared["service"].execute_plan(operation.operation_id, plan.plan_id)
    assert caught.value.error.code == "NATIVE_WORKSPACE_NOT_AVAILABLE"

    with pytest.raises(ValidationError):
        NativeRuntimeConfig(
            data_dir=str(tmp_path.resolve()),
            log_dir=str(tmp_path.resolve()),
            management_port=59020,
            management_credential_reference_id="internal/cc-connect-management-token",
            projects=[],
        )


def test_native_apply_rejects_missing_agent_executable(managed_runtime_environment, tmp_path):
    prepared = prepared_native_environment(managed_runtime_environment, tmp_path)
    prepared["service"].agent_path_lookup = lambda _command: None
    plan = prepared["service"].create_plan(prepared["request"])
    confirmation = NativeConfigurationConfirmation(
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        current_revision=plan.current_revision,
        target_revision=plan.target_revision,
        confirmation=True,
    )
    operation, _ = prepared["service"].confirm_plan(
        confirmation,
        idempotency_key=f"native-config-{uuid.uuid4().hex}",
        body=confirmation.model_dump_json().encode(),
    )
    with pytest.raises(OperationExecutionError) as caught:
        prepared["service"].execute_plan(operation.operation_id, plan.plan_id)
    assert caught.value.error.code == "NATIVE_AGENT_EXECUTABLE_NOT_AVAILABLE"


def test_runtime_secret_injector_uses_minimal_child_environment_and_audits(
    managed_runtime_environment, tmp_path, monkeypatch
):
    prepared = prepared_native_environment(managed_runtime_environment, tmp_path)
    service = prepared["service"]
    apply_native(service, prepared["request"])
    state = service.state()
    assert state.runtime_config is not None
    injector = RuntimeSecretInjector(
        managed_runtime_environment["database"], prepared["credentials"]
    )
    monkeypatch.setenv("PATH", "synthetic-path-must-not-inherit")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key-must-not-inherit")
    with injector.environment(
        state.runtime_config,
        operation_id="native-runtime-secret-test",
        product_instance_id=state.managed_state.product_instance_id,
    ) as environment:
        retained = environment
        assert environment["AIAD_TELEGRAM_CLAUDE_BOT_TOKEN"].startswith("100002:")
        assert environment["AIAD_TELEGRAM_CODEX_BOT_TOKEN"].startswith("100003:")
        assert environment["AIAD_CC_CONNECT_MANAGEMENT_TOKEN"]
        assert environment["PATH"] == "synthetic-path-must-not-inherit"
        assert "OPENAI_API_KEY" not in environment
    assert retained == {}
    with managed_runtime_environment["database"].session() as session:
        audits = list(
            session.scalars(
                select(RuntimeSecretInjectionAuditRecord).where(
                    RuntimeSecretInjectionAuditRecord.operation_id == "native-runtime-secret-test"
                )
            )
        )
    assert [item.status for item in audits] == ["injected", "released"]
    audit_json = json.dumps([item.credential_references_json for item in audits], sort_keys=True)
    assert "synthetic-token" not in audit_json


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(200, "verified"), (401, "auth_failed"), (403, "auth_failed"), (500, "unreachable")],
)
def test_runtime_management_probe_distinguishes_auth_failure(
    managed_runtime_environment, tmp_path, monkeypatch, status_code, expected
):
    prepared = prepared_native_environment(managed_runtime_environment, tmp_path)
    apply_native(prepared["service"], prepared["request"])
    state = prepared["service"].state()
    assert state.runtime_config is not None
    injector = RuntimeSecretInjector(
        managed_runtime_environment["database"], prepared["credentials"]
    )

    class Response:
        def __init__(self, code):
            self.status_code = code

    monkeypatch.setattr(
        "control_plane.cc_connect.runtime_secret_injector.httpx.get",
        lambda *_args, **_kwargs: Response(status_code),
    )
    assert injector.probe_management_status(state.runtime_config) == expected


def test_hermes_plan_is_pending_or_plan_only_and_never_takes_external_ownership(
    managed_runtime_environment, tmp_path
):
    prepared = prepared_native_environment(managed_runtime_environment, tmp_path)
    request = HermesConfigurationPlanRequest(binding_session_id=prepared["binding"].session_id)
    pending = HermesConfigurationPlanner(
        managed_runtime_environment["database"],
        prepared["bindings"],
        path_lookup=lambda _name: None,
    ).create_plan(request)
    assert pending.status == "pending_component_install"
    assert pending.writes_external_configuration is False

    installed = HermesConfigurationPlanner(
        managed_runtime_environment["database"],
        prepared["bindings"],
        path_lookup=lambda name: str(tmp_path / name),
    ).create_plan(request)
    assert installed.status == "plan_ready_external_owner"
    assert installed.management_owner == "external"
    assert installed.apply_supported is False
    assert installed.credential_reference_id == "telegram/hermes-bot-token"
    assert "TELEGRAM_BOT_TOKEN" not in installed.non_secret_environment


def test_native_lifecycle_injects_secrets_owns_updates_and_stop_releases(
    managed_runtime_environment, tmp_path, monkeypatch
):
    prepared = prepared_native_environment(managed_runtime_environment, tmp_path)
    native = prepared["service"]
    plan, _ = apply_native(native, prepared["request"])
    injector = RuntimeSecretInjector(
        managed_runtime_environment["database"], prepared["credentials"]
    )
    monkeypatch.setattr(injector, "probe_management_status", lambda _config: "verified")
    port = FakePortInspector()

    class SnapshotLauncher(FakeLauncher):
        def __call__(self, arguments, **kwargs):
            kwargs["env"] = dict(kwargs["env"])
            return super().__call__(arguments, **kwargs)

    launcher = SnapshotLauncher(port)
    identity = FakeIdentityInspector(launcher)
    lifecycle = ManagedProcessService(
        managed_runtime_environment["database"],
        managed_runtime_environment["installer"].layout,
        managed_runtime_environment["configuration"],
        version_store=managed_runtime_environment["version_store"],
        identity_inspector=identity,
        port_inspector=port,
        launcher=launcher,
        process_factory=launcher.process_factory,
        external_detector=lambda: False,
        native_configuration_service=native,
        runtime_secret_injector=injector,
        telegram_identities=prepared["identities"],
        telegram_leases=prepared["leases"],
        startup_timeout_seconds=0.08,
        stop_timeout_seconds=0.02,
        stable_window_seconds=0.01,
        poll_interval_seconds=0.001,
    )

    started = execute(
        lifecycle,
        managed_runtime_environment["database"],
        "start",
        plan.target_revision,
        "native-start-key",
    )
    assert started.status.value == "succeeded"
    assert started.result["management_api_verified"] is True
    arguments, options = launcher.calls[0]
    assert arguments[1:] == ["-config", str(native.store.runtime_path)]
    assert all("synthetic" not in item for item in arguments)
    assert options["env"]["AIAD_TELEGRAM_CLAUDE_BOT_TOKEN"].startswith("100002:")
    assert options["env"]["AIAD_TELEGRAM_CODEX_BOT_TOKEN"].startswith("100003:")
    assert options["env"]["PATH"] == os.environ["PATH"]
    assert prepared["leases"].get("claude").owner == UpdateOwner.CC_CONNECT_RUNTIME
    assert prepared["leases"].get("codex").owner == UpdateOwner.CC_CONNECT_RUNTIME

    stopped = execute(
        lifecycle,
        managed_runtime_environment["database"],
        "stop",
        plan.target_revision,
        "native-stop-key",
    )
    assert stopped.status.value == "succeeded"
    assert prepared["leases"].get("claude").owner == UpdateOwner.NONE
    assert prepared["leases"].get("codex").owner == UpdateOwner.NONE

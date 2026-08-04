from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from control_plane.cc_connect.native_config_models import (
    NativeConfigurationConfirmation,
    NativeConfigurationPlanRequest,
    NativeRuntimeConfig,
)
from control_plane.cc_connect.native_configuration_service import (
    CcConnectNativeConfigurationService,
)
from control_plane.cc_connect.runtime_secret_injector import RuntimeSecretInjector
from control_plane.hermes.config_renderer import HermesConfigurationPlanner
from control_plane.hermes.models import HermesConfigurationPlanRequest
from control_plane.lifecycle.managed_process import ManagedProcessService
from control_plane.operations import OperationExecutionError
from control_plane.persistence.models import (
    NativeConfigurationBackupRecord,
    RuntimeSecretInjectionAuditRecord,
)
from control_plane.telegram.models import UpdateOwner

from .telegram_helpers import build_telegram_services, complete_binding
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
    assert plan.renderer_version == "cc-connect-fc315d2-native-v1"


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

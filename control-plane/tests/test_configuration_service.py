from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from control_plane.application.operation_store import OperationStore
from control_plane.configuration.config_store import ConfigurationError
from control_plane.configuration.models import (
    ConfigurationConfirmationRequest,
    ConfigurationPlanRequest,
)
from control_plane.domain.models import OperationStatus
from control_plane.installer.artifacts import InstallerError
from control_plane.persistence.models import PendingRepairRecord


def confirm_and_apply(environment, plan, *, key: str | None = None):
    service = environment["configuration"]
    confirmation = ConfigurationConfirmationRequest(
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        current_revision=plan.current_revision,
        target_revision=plan.target_revision,
        confirmation=True,
    )
    body = confirmation.model_dump_json().encode()
    operation, reused = service.confirm_plan(
        confirmation,
        idempotency_key=key or f"config-{uuid.uuid4().hex}",
        body=body,
    )
    if not reused:
        service.execute_plan(operation.operation_id, plan.plan_id)
    with environment["database"].session() as session:
        persisted = OperationStore(session).get(operation.operation_id)
    assert persisted is not None
    return persisted, confirmation, body, reused


def test_first_write_is_revisioned_atomic_non_secret_and_unicode_safe(
    managed_runtime_environment,
):
    environment = managed_runtime_environment
    service = environment["configuration"]
    plan = service.create_plan(ConfigurationPlanRequest())
    operation, confirmation, body, reused = confirm_and_apply(
        environment, plan, key="configuration-first-key"
    )
    assert not reused
    assert operation.status == OperationStatus.SUCCEEDED
    state = service.state()
    assert state.status == "valid"
    assert state.revision == 1
    assert state.configuration is not None
    assert state.configuration.telegram.enabled is False
    assert state.configuration.listen_host == "127.0.0.1"
    assert state.configuration.secret_refs[0].required is False
    assert "中文" in str(service.store.path)
    raw = service.store.path.read_text(encoding="utf-8")
    assert "token =" not in raw.casefold()
    assert "api_key" not in raw.casefold()
    assert "123456789:" not in raw

    retried, retry_reused = service.confirm_plan(
        confirmation,
        idempotency_key="configuration-first-key",
        body=body,
    )
    assert retry_reused
    assert retried.operation_id == operation.operation_id
    assert service.state().revision == 1


def test_confirmation_binds_digest_and_all_revisions(managed_runtime_environment):
    service = managed_runtime_environment["configuration"]
    plan = service.create_plan(ConfigurationPlanRequest())
    with pytest.raises(InstallerError) as captured:
        service.confirm_plan(
            ConfigurationConfirmationRequest(
                plan_id=plan.plan_id,
                plan_digest="sha256:" + "0" * 64,
                current_revision=plan.current_revision,
                target_revision=plan.target_revision,
                confirmation=True,
            ),
            idempotency_key="configuration-digest-key",
            body=b"mismatch",
        )
    assert captured.value.code == "CONFIGURATION_CONFIRMATION_MISMATCH"


def test_expired_plan_is_rejected_before_operation_creation(
    managed_runtime_environment, monkeypatch
):
    service = managed_runtime_environment["configuration"]
    plan = service.create_plan(ConfigurationPlanRequest())
    monkeypatch.setattr("control_plane.configuration.service._is_expired", lambda _value: True)
    with pytest.raises(InstallerError) as captured:
        service.confirm_plan(
            ConfigurationConfirmationRequest(
                plan_id=plan.plan_id,
                plan_digest=plan.plan_digest,
                current_revision=plan.current_revision,
                target_revision=plan.target_revision,
                confirmation=True,
            ),
            idempotency_key="configuration-expired-key",
            body=b"expired",
        )
    assert captured.value.code == "CONFIGURATION_PLAN_EXPIRED"


def test_two_confirmed_plans_detect_revision_conflict(managed_runtime_environment):
    environment = managed_runtime_environment
    service = environment["configuration"]
    first = service.create_plan(ConfigurationPlanRequest(listen_port=59010))
    second = service.create_plan(ConfigurationPlanRequest(listen_port=59011))

    def confirm(plan, key):
        request = ConfigurationConfirmationRequest(
            plan_id=plan.plan_id,
            plan_digest=plan.plan_digest,
            current_revision=plan.current_revision,
            target_revision=plan.target_revision,
            confirmation=True,
        )
        return service.confirm_plan(
            request,
            idempotency_key=key,
            body=request.model_dump_json().encode(),
        )[0]

    first_operation = confirm(first, "configuration-race-key-1")
    second_operation = confirm(second, "configuration-race-key-2")
    service.execute_plan(first_operation.operation_id, first.plan_id)
    service.execute_plan(second_operation.operation_id, second.plan_id)
    with environment["database"].session() as session:
        rejected = OperationStore(session).get(second_operation.operation_id)
    assert rejected is not None and rejected.status == OperationStatus.FAILED
    assert rejected.error and rejected.error.code == "CONFIGURATION_REVISION_CONFLICT"
    assert service.state().revision == 1


def test_manual_modification_is_detected_and_blocks_new_plan(managed_runtime_environment):
    environment = managed_runtime_environment
    service = environment["configuration"]
    completed, *_ = confirm_and_apply(environment, service.create_plan(ConfigurationPlanRequest()))
    assert completed.status == OperationStatus.SUCCEEDED
    with service.store.path.open("a", encoding="utf-8") as handle:
        handle.write("\n# manual drift\n")
    state = service.state()
    assert state.status == "drifted"
    assert state.diagnostic_code == "CONFIGURATION_MANUAL_DRIFT"
    with pytest.raises(InstallerError) as captured:
        service.create_plan(ConfigurationPlanRequest())
    assert captured.value.code == "CONFIGURATION_MANUAL_DRIFT"


def test_locked_atomic_replace_fails_without_partial_file(managed_runtime_environment, monkeypatch):
    environment = managed_runtime_environment
    service = environment["configuration"]
    plan = service.create_plan(ConfigurationPlanRequest())

    def locked(_source, _target):
        raise PermissionError("sharing violation")

    monkeypatch.setattr("control_plane.configuration.config_store.os.replace", locked)
    operation, *_ = confirm_and_apply(environment, plan)
    assert operation.status == OperationStatus.FAILED
    assert operation.error and operation.error.code == "CONFIGURATION_FILE_LOCKED"
    assert not service.store.path.exists()


def test_post_write_parse_failure_restores_previous_bytes(managed_runtime_environment, monkeypatch):
    environment = managed_runtime_environment
    service = environment["configuration"]
    first, *_ = confirm_and_apply(environment, service.create_plan(ConfigurationPlanRequest()))
    assert first.status == OperationStatus.SUCCEEDED
    previous = service.store.path.read_bytes()
    plan = service.create_plan(ConfigurationPlanRequest(listen_port=59012))

    def invalid(_data):
        raise ValueError("synthetic TOML parse failure")

    monkeypatch.setattr(service.store, "post_write_validator", invalid)
    operation, *_ = confirm_and_apply(environment, plan)
    assert operation.status == OperationStatus.FAILED
    assert operation.error
    assert operation.error.code == "CONFIGURATION_POST_WRITE_VALIDATION_FAILED"
    assert service.store.path.read_bytes() == previous
    assert service.state().revision == 1


def test_rollback_plan_creates_new_monotonic_revision(managed_runtime_environment):
    environment = managed_runtime_environment
    service = environment["configuration"]
    revision_one, *_ = confirm_and_apply(
        environment, service.create_plan(ConfigurationPlanRequest(listen_port=59013))
    )
    assert revision_one.status == OperationStatus.SUCCEEDED
    revision_two, *_ = confirm_and_apply(
        environment, service.create_plan(ConfigurationPlanRequest(listen_port=59014))
    )
    assert revision_two.status == OperationStatus.SUCCEEDED
    rollback = service.create_plan(ConfigurationPlanRequest(rollback_to_revision=1))
    assert rollback.rollback_to_revision == 1
    revision_three, *_ = confirm_and_apply(environment, rollback)
    assert revision_three.status == OperationStatus.SUCCEEDED
    state = service.state()
    assert state.revision == 3
    assert state.configuration and state.configuration.listen_port == 59013


def test_failed_rollback_is_persisted_as_pending_repair(managed_runtime_environment, monkeypatch):
    environment = managed_runtime_environment
    service = environment["configuration"]
    confirm_and_apply(environment, service.create_plan(ConfigurationPlanRequest()))
    plan = service.create_plan(ConfigurationPlanRequest(listen_port=59015))

    def invalid(_data):
        raise ValueError("post-write schema failure")

    def rollback_failed(_previous):
        raise ConfigurationError(
            "CONFIGURATION_ROLLBACK_FAILED",
            "synthetic rollback failure",
            recovery_actions=["inspect_pending_repair"],
        )

    monkeypatch.setattr(service.store, "post_write_validator", invalid)
    monkeypatch.setattr(service.store, "_restore_previous", rollback_failed)
    operation, *_ = confirm_and_apply(environment, plan)
    assert operation.status == OperationStatus.FAILED
    assert operation.error and operation.error.code == "CONFIGURATION_ROLLBACK_FAILED"
    with environment["database"].session() as session:
        repairs = list(session.query(PendingRepairRecord).all())
    assert len(repairs) == 1
    assert repairs[0].status == "pending"


def test_configuration_path_rejects_link_or_junction_component(
    managed_runtime_environment, monkeypatch
):
    service = managed_runtime_environment["configuration"]
    config_dir = service.layout.root / "state" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    original = Path.is_symlink

    def pretend_link(path: Path):
        if path == config_dir:
            return True
        return original(path)

    monkeypatch.setattr(Path, "is_symlink", pretend_link)
    with pytest.raises(InstallerError) as captured:
        service.store.read_bytes()
    assert captured.value.code in {"INSTALL_PATH_UNSAFE", "CONFIGURATION_PATH_UNSAFE"}

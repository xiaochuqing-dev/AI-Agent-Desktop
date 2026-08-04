from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from control_plane.application.event_log import EventLog
from control_plane.application.operation_store import OperationStore
from control_plane.domain.models import OperationStatus
from control_plane.infrastructure.config import Settings
from control_plane.installer.artifacts import InstallerError
from control_plane.installer.models import (
    ArtifactManifest,
    InstallConfirmationRequest,
    InstallPlanRequest,
    RestoreRequest,
    UninstallRequest,
)
from control_plane.installer.service import CcConnectInstaller
from control_plane.persistence.models import (
    ComponentVersionRecord,
    InstallationLeaseRecord,
    PendingCleanupRecord,
)
from control_plane.persistence.session import Database

from .installer_helpers import manifest_payload, write_test_bundle


@pytest.fixture
def installer_environment(tmp_path, monkeypatch):
    bundle, manifest = write_test_bundle(tmp_path / "可信 产物 (bundle)")
    settings = Settings(
        data_dir=str(tmp_path / "隔离 LocalAppData (验收)"),
        trusted_artifact_dir=str(bundle),
    )
    database = Database(settings)

    def successful_probe(_path, probed_manifest, *, cancel_check=None, **_kwargs):
        if cancel_check:
            cancel_check()
        return f"{probed_manifest.version} {probed_manifest.source_commit[:7]}"

    monkeypatch.setattr(
        "control_plane.installer.service.run_isolated_version_probe", successful_probe
    )
    installer = CcConnectInstaller(settings, database, EventLog())
    return installer, database, manifest


def make_plan(installer: CcConnectInstaller, manifest: ArtifactManifest):
    return installer.create_plan(
        InstallPlanRequest(
            source_ref="trusted-local-bundle",
            expected_digest=f"sha256:{manifest.artifact_sha256}",
        )
    )


def confirm_plan(installer: CcConnectInstaller, plan, key: str):
    confirmation = InstallConfirmationRequest(
        requested_version=plan.version,
        source_ref=plan.source.source_ref,
        expected_digest=f"sha256:{plan.sha256}",
        confirm=True,
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        confirmation=True,
    )
    body = confirmation.model_dump_json().encode()
    operation, reused = installer.confirm_install(confirmation, idempotency_key=key, body=body)
    return operation, confirmation, body, reused


def load_operation(database: Database, operation_id: str):
    with database.session() as session:
        return OperationStore(session).get(operation_id)


def install_once(installer, database, manifest, *, key="install-key-0001"):
    plan = make_plan(installer, manifest)
    operation, confirmation, body, reused = confirm_plan(installer, plan, key)
    assert not reused
    installer.execute_install(operation.operation_id, plan.plan_id, "test")
    completed = load_operation(database, operation.operation_id)
    assert completed is not None and completed.status == OperationStatus.SUCCEEDED
    return plan, operation, confirmation, body, completed


def test_first_install_repeat_and_idempotency(installer_environment):
    installer, database, manifest = installer_environment
    plan, operation, confirmation, body, completed = install_once(installer, database, manifest)
    current = installer.layout.read_current()
    assert current and current["artifact_id"] == manifest.artifact_id
    target = installer.layout.version_dir(manifest.artifact_id)
    first_record = json.loads((target / "install-record.json").read_text(encoding="utf-8"))
    retried, reused = installer.confirm_install(
        confirmation, idempotency_key="install-key-0001", body=body
    )
    assert reused and retried.operation_id == operation.operation_id

    second_plan = make_plan(installer, manifest)
    second, _, _, _ = confirm_plan(installer, second_plan, "install-key-0002")
    installer.execute_install(second.operation_id, second_plan.plan_id, "test")
    second_completed = load_operation(database, second.operation_id)
    assert second_completed and second_completed.result["already_installed"] is True
    assert installer.layout.read_current() == current
    assert json.loads((target / "install-record.json").read_text(encoding="utf-8")) == (
        first_record
    )
    assert [event.phase for event in installer.list_audit_events(operation.operation_id)][-1] == (
        "completed"
    )


def test_two_concurrent_install_confirmations_have_one_executor(installer_environment):
    installer, _database, manifest = installer_environment
    first_plan = make_plan(installer, manifest)
    second_plan = make_plan(installer, manifest)
    confirm_plan(installer, first_plan, "concurrent-key-1")
    with pytest.raises(InstallerError) as captured:
        confirm_plan(installer, second_plan, "concurrent-key-2")
    assert captured.value.code == "INSTALLATION_ALREADY_RUNNING"


@pytest.mark.parametrize("phase", ["acquiring", "validating"])
def test_cancellation_at_safe_checkpoint_is_not_overreported(installer_environment, phase):
    installer, database, manifest = installer_environment
    plan = make_plan(installer, manifest)
    operation, _, _, _ = confirm_plan(installer, plan, f"cancel-{phase}-key")

    def request_cancel(observed_phase: str, operation_id: str) -> None:
        if observed_phase != phase:
            return
        with database.session() as session:
            OperationStore(session).transition(
                operation_id,
                status=OperationStatus.CANCEL_REQUESTED,
                phase="cancel_requested",
                message="test cancellation",
            )

    installer.fault_injector = request_cancel
    installer.execute_install(operation.operation_id, plan.plan_id, "test")
    completed = load_operation(database, operation.operation_id)
    assert completed and completed.status == OperationStatus.CANCELED
    assert installer.layout.read_current() is None


def test_cancellation_after_point_of_no_return_completes_truthfully(installer_environment):
    installer, database, manifest = installer_environment
    plan = make_plan(installer, manifest)
    operation, _, _, _ = confirm_plan(installer, plan, "cancel-after-ponr")

    def request_cancel(phase: str, operation_id: str) -> None:
        if phase != "activating":
            return
        with database.session() as session:
            store = OperationStore(session)
            current = store.get(operation_id)
            if not current or not current.progress.point_of_no_return:
                return
            store.transition(
                operation_id,
                status=OperationStatus.CANCEL_REQUESTED,
                phase="cancel_requested",
                message="too late to stop atomic activation",
            )
        installer.audit_cancel_requested(operation_id, point_of_no_return=True)

    installer.fault_injector = request_cancel
    installer.execute_install(operation.operation_id, plan.plan_id, "test")
    completed = load_operation(database, operation.operation_id)
    assert completed and completed.status == OperationStatus.SUCCEEDED
    assert any(
        event.event_type == "com.aiagentdesktop.operation.cancel_requested.v1"
        for event in installer.list_audit_events(operation.operation_id)
    )


def test_disk_space_and_staging_write_failures_are_diagnostic(installer_environment, monkeypatch):
    installer, database, manifest = installer_environment
    plan = make_plan(installer, manifest)
    operation, _, _, _ = confirm_plan(installer, plan, "disk-space-key-01")
    import control_plane.installer.service as installer_service

    original_disk_usage = installer_service.shutil.disk_usage
    monkeypatch.setattr(
        installer_service.shutil, "disk_usage", lambda _path: SimpleNamespace(free=0)
    )
    installer.execute_install(operation.operation_id, plan.plan_id, "test")
    failed = load_operation(database, operation.operation_id)
    assert failed and failed.error and failed.error.code == "DISK_SPACE_INSUFFICIENT"

    monkeypatch.setattr(installer_service.shutil, "disk_usage", original_disk_usage)
    second_plan = make_plan(installer, manifest)
    second, _, _, _ = confirm_plan(installer, second_plan, "staging-write-key")

    def unwritable() -> None:
        raise InstallerError(
            "STAGING_DIRECTORY_NOT_WRITABLE",
            "Staging is not writable.",
            recovery_actions=["choose_writable_product_data"],
        )

    monkeypatch.setattr(installer.layout, "ensure", unwritable)
    installer.execute_install(second.operation_id, second_plan.plan_id, "test")
    failed = load_operation(database, second.operation_id)
    assert failed and failed.error and failed.error.code == "STAGING_DIRECTORY_NOT_WRITABLE"


def test_health_failure_and_pre_activation_crash_never_change_current(
    installer_environment, monkeypatch
):
    installer, database, manifest = installer_environment

    def fail_health(*_args, **_kwargs):
        raise InstallerError("HEALTH_PROBE_FAILED", "synthetic failure")

    import control_plane.installer.service as installer_service

    successful_probe = installer_service.run_isolated_version_probe
    monkeypatch.setattr(installer_service, "run_isolated_version_probe", fail_health)
    plan = make_plan(installer, manifest)
    operation, _, _, _ = confirm_plan(installer, plan, "health-failure-key")
    installer.execute_install(operation.operation_id, plan.plan_id, "test")
    failed = load_operation(database, operation.operation_id)
    assert failed and failed.error and failed.error.code == "HEALTH_PROBE_FAILED"
    assert installer.layout.read_current() is None

    monkeypatch.setattr(installer_service, "run_isolated_version_probe", successful_probe)
    second_plan = make_plan(installer, manifest)
    second, _, _, _ = confirm_plan(installer, second_plan, "preactivation-crash")

    def crash(phase: str, _operation_id: str) -> None:
        if phase == "validating":
            raise RuntimeError("synthetic crash")

    installer.fault_injector = crash
    installer.execute_install(second.operation_id, second_plan.plan_id, "test")
    failed = load_operation(database, second.operation_id)
    assert failed and failed.error and failed.error.code == "INSTALLATION_INTERNAL_ERROR"
    assert installer.layout.read_current() is None


def test_current_write_failure_and_automatic_rollback(installer_environment, monkeypatch):
    installer, database, manifest = installer_environment
    plan = make_plan(installer, manifest)
    operation, _, _, _ = confirm_plan(installer, plan, "current-write-failure")

    def fail_write(_payload) -> None:
        raise InstallerError("ATOMIC_WRITE_FAILED", "synthetic lock")

    original_write_current = installer.layout.write_current
    monkeypatch.setattr(installer.layout, "write_current", fail_write)
    installer.execute_install(operation.operation_id, plan.plan_id, "test")
    failed = load_operation(database, operation.operation_id)
    assert failed and failed.error and failed.error.code == "ATOMIC_WRITE_FAILED"
    assert not installer.layout.version_dir(manifest.artifact_id).exists()

    monkeypatch.setattr(installer.layout, "write_current", original_write_current)
    second_plan = make_plan(installer, manifest)
    second, _, _, _ = confirm_plan(installer, second_plan, "rollback-success-key")

    def fail_after_activation(*_args, **_kwargs) -> None:
        raise InstallerError("POST_ACTIVATION_FAILURE", "synthetic failure")

    monkeypatch.setattr(installer, "_record_install_success", fail_after_activation)
    installer.execute_install(second.operation_id, second_plan.plan_id, "test")
    rolled_back = load_operation(database, second.operation_id)
    assert rolled_back and rolled_back.progress.phase == "rolled_back"
    assert installer.layout.read_current() is None


def test_rollback_failure_is_explicit_and_preserves_snapshot(installer_environment, monkeypatch):
    installer, database, manifest = installer_environment
    plan = make_plan(installer, manifest)
    operation, _, _, _ = confirm_plan(installer, plan, "rollback-failure-key")

    def fail_record(*_args, **_kwargs) -> None:
        raise InstallerError("POST_ACTIVATION_FAILURE", "synthetic failure")

    def fail_rollback(_snapshot) -> None:
        raise InstallerError("ROLLBACK_CURRENT_FAILED", "synthetic lock")

    monkeypatch.setattr(installer, "_record_install_success", fail_record)
    monkeypatch.setattr(installer, "_restore_snapshot", fail_rollback)
    installer.execute_install(operation.operation_id, plan.plan_id, "test")
    failed = load_operation(database, operation.operation_id)
    assert failed and failed.progress.phase == "rollback_failed"
    assert failed.error and failed.error.code == "ROLLBACK_FAILED"
    assert installer.layout.backup_dir(operation.operation_id).exists()


def test_restart_recovers_failed_operation_and_releases_lease(installer_environment):
    installer, database, manifest = installer_environment
    install_once(installer, database, manifest, key="restart-base-install")
    original = installer.layout.read_current()
    plan = make_plan(installer, manifest)
    operation, _, _, _ = confirm_plan(installer, plan, "restart-interrupted")
    snapshot = installer._capture_snapshot(operation.operation_id, plan, 10**9)
    installer._persist_snapshot(snapshot)
    interrupted = dict(original or {})
    interrupted["operation_id"] = operation.operation_id
    interrupted["revision"] = "interrupted"
    installer.layout.write_current(interrupted)
    with database.session() as session:
        OperationStore(session).recover_on_startup()
    installer.recover_interrupted_operations()
    assert installer.layout.read_current() == original
    with database.session() as session:
        assert session.get(InstallationLeaseRecord, "cc-connect") is None


def _add_previous_version(installer, database, manifest) -> ArtifactManifest:
    artifact = (Path(installer.settings.trusted_artifact_dir) / "cc-connect.exe").read_bytes()
    payload = manifest_payload(artifact)
    payload["artifact_id"] = "cc-connect-previous-windows-amd64"
    payload["version"] = "v1.4.0-previous"
    payload["source_commit"] = "1" * 40
    previous = ArtifactManifest.model_validate(payload)
    target = installer.layout.version_dir(previous.artifact_id)
    target.mkdir(parents=True)
    (target / previous.artifact_filename).write_bytes(artifact)
    (target / "cc-connect-artifact-manifest.json").write_text(
        json.dumps(previous.model_dump(mode="json"), sort_keys=True), encoding="utf-8"
    )
    (target / "install-record.json").write_text(
        json.dumps(
            {
                "component_id": "cc-connect",
                "artifact_id": previous.artifact_id,
                "artifact_sha256": previous.artifact_sha256,
                "operation_id": "historic-operation",
            }
        ),
        encoding="utf-8",
    )
    with database.session() as session:
        session.add(
            ComponentVersionRecord(
                artifact_id=previous.artifact_id,
                component_id="cc-connect",
                version=previous.version,
                relative_path=f"versions/{previous.artifact_id}",
                artifact_sha256=previous.artifact_sha256,
                artifact_size=previous.artifact_size,
                status="installed",
                installed_at=datetime.now(UTC),
                removed_at=None,
            )
        )
    return previous


def test_restore_previous_then_uninstall_noncurrent_but_not_current(installer_environment):
    installer, database, manifest = installer_environment
    install_once(installer, database, manifest, key="restore-base-install")
    previous = _add_previous_version(installer, database, manifest)
    current = installer.layout.read_current()
    assert current
    current["previous_artifact_id"] = previous.artifact_id
    installer.layout.write_current(current)

    restore = RestoreRequest(confirm=True)
    operation, _ = installer.create_restore_operation(
        restore, idempotency_key="restore-previous-key", body=restore.model_dump_json().encode()
    )
    installer.execute_restore(operation.operation_id, restore, "test")
    restored = load_operation(database, operation.operation_id)
    assert restored and restored.status == OperationStatus.SUCCEEDED
    assert installer.layout.read_current()["artifact_id"] == previous.artifact_id

    uninstall = UninstallRequest(artifact_id=manifest.artifact_id, confirm=True)
    removal, _ = installer.create_uninstall_operation(
        uninstall,
        idempotency_key="uninstall-noncurrent",
        body=uninstall.model_dump_json().encode(),
    )
    installer.execute_uninstall(removal.operation_id, uninstall, "test")
    removed = load_operation(database, removal.operation_id)
    assert removed and removed.status == OperationStatus.SUCCEEDED
    assert installer.layout.version_dir(previous.artifact_id).exists()

    current_uninstall = UninstallRequest(artifact_id=previous.artifact_id, confirm=True)
    rejected, _ = installer.create_uninstall_operation(
        current_uninstall,
        idempotency_key="uninstall-current-key",
        body=current_uninstall.model_dump_json().encode(),
    )
    installer.execute_uninstall(rejected.operation_id, current_uninstall, "test")
    rejected_operation = load_operation(database, rejected.operation_id)
    assert rejected_operation and rejected_operation.error
    assert rejected_operation.error.code == "CURRENT_VERSION_IN_USE"


def test_locked_file_becomes_pending_cleanup_then_retries(installer_environment, monkeypatch):
    installer, database, manifest = installer_environment
    install_once(installer, database, manifest, key="pending-base-install")
    previous = _add_previous_version(installer, database, manifest)
    target = installer.layout.version_dir(previous.artifact_id)
    original_rmtree = __import__("shutil").rmtree

    def locked(path, *args, **kwargs):
        if Path(path) == target:
            raise PermissionError("locked")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("control_plane.installer.service.shutil.rmtree", locked)
    request = UninstallRequest(artifact_id=previous.artifact_id, confirm=True)
    operation, _ = installer.create_uninstall_operation(
        request,
        idempotency_key="pending-cleanup-key",
        body=request.model_dump_json().encode(),
    )
    installer.execute_uninstall(operation.operation_id, request, "test")
    pending = load_operation(database, operation.operation_id)
    assert pending and pending.progress.phase == "pending_cleanup"
    with database.session() as session:
        assert session.query(PendingCleanupRecord).count() == 1

    monkeypatch.setattr("control_plane.installer.service.shutil.rmtree", original_rmtree)
    assert installer.retry_pending_cleanup() == 1
    assert not target.exists()
    assert installer.retry_pending_cleanup() == 0


def test_external_management_owner_is_preserved(installer_environment, monkeypatch):
    installer, database, manifest = installer_environment
    monkeypatch.setattr(installer, "_external_cc_connect_detected", lambda: True)
    plan = make_plan(installer, manifest)
    assert plan.current_owner == "external"
    operation, _, _, _ = confirm_plan(installer, plan, "external-owner-key")
    installer.execute_install(operation.operation_id, plan.plan_id, "test")
    completed = load_operation(database, operation.operation_id)
    assert completed and completed.result["management_owner"] == "external"
    assert completed.result["lifecycle_takeover"] is False


def test_persisted_plan_tampering_is_blocked_before_activation(installer_environment):
    installer, database, manifest = installer_environment
    plan = make_plan(installer, manifest)
    operation, _, _, _ = confirm_plan(installer, plan, "tampered-plan-key")
    with database.session() as session:
        from control_plane.persistence.models import InstallPlanRecord

        record = session.get(InstallPlanRecord, plan.plan_id)
        assert record
        payload = json.loads(record.plan_json)
        payload["risk"] = "low"
        record.plan_json = json.dumps(payload)
    installer.execute_install(operation.operation_id, plan.plan_id, "test")
    failed = load_operation(database, operation.operation_id)
    assert failed and failed.error and failed.error.code == "INSTALL_PLAN_DIGEST_MISMATCH"


def test_unrelated_current_change_is_not_overwritten_during_failure(installer_environment):
    installer, database, manifest = installer_environment
    plan = make_plan(installer, manifest)
    operation, _, _, _ = confirm_plan(installer, plan, "current-race-key")
    replacement = {
        "schema_version": "1.0",
        "artifact_id": "external-product-update",
        "version": "external",
        "artifact_sha256": "b" * 64,
        "previous_artifact_id": None,
        "revision": "external",
    }
    changed = False

    def change_current(phase: str, _operation_id: str) -> None:
        nonlocal changed
        if phase == "activating" and not changed:
            changed = True
            installer.layout.write_current(replacement)

    installer.fault_injector = change_current
    installer.execute_install(operation.operation_id, plan.plan_id, "test")
    failed = load_operation(database, operation.operation_id)
    assert failed and failed.error and failed.error.code == "CURRENT_POINTER_CHANGED"
    assert installer.layout.read_current() == replacement

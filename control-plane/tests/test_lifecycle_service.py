from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import psutil

from control_plane.application.operation_store import OperationStore
from control_plane.configuration.models import (
    ConfigurationConfirmationRequest,
    ConfigurationPlanRequest,
    LifecycleOwner,
)
from control_plane.domain.models import OperationStatus
from control_plane.lifecycle.managed_process import (
    WINDOWS_CREATE_NEW_PROCESS_GROUP,
    WINDOWS_CREATE_NO_WINDOW,
    ManagedProcessService,
)
from control_plane.lifecycle.models import (
    IdentityVerification,
    LifecycleActionRequest,
    PortOwnershipEvidence,
    ProcessIdentity,
)
from control_plane.lifecycle.process_identity import command_digest
from control_plane.persistence.models import ManagedProcessRecord


class FakePortInspector:
    def __init__(self) -> None:
        self.owner_pid: int | None = None
        self.unknown = False

    def choose_available(self) -> int:
        return 59020

    def validate_controlled_port(self, host: str, port: int) -> None:
        assert host == "127.0.0.1"
        assert 59000 <= port <= 59999

    def is_available(self, host: str, port: int) -> bool:
        self.validate_controlled_port(host, port)
        return self.owner_pid is None and not self.unknown

    def inspect(
        self, host: str, port: int, expected_pid: int | None = None
    ) -> PortOwnershipEvidence:
        self.validate_controlled_port(host, port)
        if self.unknown:
            return PortOwnershipEvidence(
                listen_port=port,
                status="unknown",
                expected_pid=expected_pid,
            )
        if self.owner_pid is None:
            return PortOwnershipEvidence(
                listen_port=port,
                status="free",
                expected_pid=expected_pid,
            )
        if expected_pid == self.owner_pid:
            return PortOwnershipEvidence(
                listen_port=port,
                status="owned",
                owner_pid=self.owner_pid,
                expected_pid=expected_pid,
            )
        return PortOwnershipEvidence(
            listen_port=port,
            status="conflict",
            owner_pid=self.owner_pid,
            expected_pid=expected_pid,
        )


class FakeProcess:
    def __init__(self, pid: int, port: FakePortInspector) -> None:
        self.pid = pid
        self.port = port
        self.running = True
        self.returncode: int | None = None
        self.signals: list[int] = []
        self.graceful = True

    def poll(self):
        return None if self.running else self.returncode

    def is_running(self):
        return self.running

    def children(self, recursive: bool = True):
        assert recursive
        return []

    def send_signal(self, value: int):
        self.signals.append(value)
        if self.graceful:
            self.force_exit(0)

    def wait(self, timeout: float | None = None):
        if self.running:
            raise psutil.TimeoutExpired(timeout or 0, self.pid)
        return self.returncode

    def terminate(self):
        self.force_exit(0)

    def kill(self):
        self.force_exit(-9)

    def force_exit(self, code: int):
        self.running = False
        self.returncode = code
        if self.port.owner_pid == self.pid:
            self.port.owner_pid = None


class FakeLauncher:
    def __init__(
        self,
        port: FakePortInspector,
        *,
        claim_port: bool = True,
        conflicting_pid: int | None = None,
    ) -> None:
        self.port = port
        self.claim_port = claim_port
        self.conflicting_pid = conflicting_pid
        self.processes: dict[int, FakeProcess] = {}
        self.calls: list[tuple[list[str], dict]] = []
        self.next_pid = 41000

    def __call__(self, arguments, **kwargs):
        pid = self.next_pid
        self.next_pid += 1
        process = FakeProcess(pid, self.port)
        self.processes[pid] = process
        self.calls.append((list(arguments), kwargs))
        if self.conflicting_pid is not None:
            self.port.owner_pid = self.conflicting_pid
        elif self.claim_port:
            self.port.owner_pid = pid
        return process

    def process_factory(self, pid: int):
        process = self.processes.get(pid)
        if process is None:
            raise psutil.NoSuchProcess(pid)
        return process


class FakeIdentityInspector:
    def __init__(self, launcher: FakeLauncher) -> None:
        self.launcher = launcher
        self.override: IdentityVerification | None = None

    def capture(self, **values):
        arguments = values["expected_arguments"]
        return ProcessIdentity(
            component_id="cc-connect",
            product_instance_id=values["product_instance_id"],
            artifact_id=values["artifact_id"],
            executable_path=str(Path(values["expected_executable"]).resolve()),
            executable_sha256=values["expected_sha256"],
            pid=values["pid"],
            process_create_time=f"{time.time() - 1:.6f}",
            parent_pid=os.getpid(),
            start_command_digest=command_digest(arguments),
            configuration_revision=values["configuration_revision"],
            listen_host=values["listen_host"],
            listen_port=values["listen_port"],
            lifecycle_owner=LifecycleOwner.PRODUCT,
            operation_id=values["operation_id"],
        )

    def verify(self, identity: ProcessIdentity):
        if self.override is not None:
            return self.override
        process = self.launcher.processes.get(identity.pid)
        if process is None or not process.running:
            return IdentityVerification(status="missing", checks={"process_exists": False})
        return IdentityVerification(
            status="verified",
            checks={
                "process_exists": True,
                "create_time": True,
                "executable_path": True,
                "executable_sha256": True,
                "parent_pid": True,
                "start_command_digest": True,
            },
        )


def apply_configuration(environment, *, port: int = 59020) -> int:
    service = environment["configuration"]
    plan = service.create_plan(ConfigurationPlanRequest(listen_port=port))
    confirmation = ConfigurationConfirmationRequest(
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        current_revision=plan.current_revision,
        target_revision=plan.target_revision,
        confirmation=True,
    )
    operation, _ = service.confirm_plan(
        confirmation,
        idempotency_key=f"lifecycle-config-{uuid.uuid4().hex}",
        body=confirmation.model_dump_json().encode(),
    )
    service.execute_plan(operation.operation_id, plan.plan_id)
    return plan.target_revision


def fake_service(environment, *, claim_port=True, conflicting_pid=None):
    port = FakePortInspector()
    launcher = FakeLauncher(port, claim_port=claim_port, conflicting_pid=conflicting_pid)
    identity = FakeIdentityInspector(launcher)
    service = ManagedProcessService(
        environment["database"],
        environment["installer"].layout,
        environment["configuration"],
        version_store=environment["version_store"],
        identity_inspector=identity,
        port_inspector=port,
        launcher=launcher,
        process_factory=launcher.process_factory,
        external_detector=lambda: False,
        startup_timeout_seconds=0.08,
        stop_timeout_seconds=0.02,
        stable_window_seconds=0.01,
        poll_interval_seconds=0.001,
    )
    return service, port, launcher, identity


def execute(service, database, action: str, revision: int, key: str):
    request = LifecycleActionRequest(configuration_revision=revision, confirmation=True)
    operation, _ = service.create_operation(
        action,
        request,
        idempotency_key=key.ljust(16, "x"),
        body=request.model_dump_json().encode(),
    )
    service.execute_action(operation.operation_id, action, request)
    with database.session() as session:
        persisted = OperationStore(session).get(operation.operation_id)
    assert persisted is not None
    return persisted


def test_start_repeat_stop_restart_and_partial_health(managed_runtime_environment):
    environment = managed_runtime_environment
    revision = apply_configuration(environment)
    service, port, launcher, _identity = fake_service(environment)
    started = execute(service, environment["database"], "start", revision, "start-first-key")
    assert started.status == OperationStatus.SUCCEEDED
    assert started.result["health"] == "partial"
    first_pid = started.result["pid"]
    status = service.status()
    assert status.observed_state == "running_partial"
    assert status.health.deep_health == "unsupported"
    assert status.health.local_endpoint_status == "unsupported"
    assert status.port_ownership and status.port_ownership.owner_pid == first_pid

    repeated = execute(service, environment["database"], "start", revision, "start-repeat-key")
    assert repeated.status == OperationStatus.SUCCEEDED
    assert repeated.result["already_running"] is True
    assert len(launcher.calls) == 1

    stopped = execute(service, environment["database"], "stop", revision, "stop-first-key")
    assert stopped.status == OperationStatus.SUCCEEDED
    assert stopped.result["port_released"] is True
    assert service.status().observed_state == "stopped"
    repeated_stop = execute(service, environment["database"], "stop", revision, "stop-repeat-key")
    assert repeated_stop.result["already_stopped"] is True

    execute(service, environment["database"], "start", revision, "start-for-restart")
    restarted = execute(service, environment["database"], "restart", revision, "restart-key-0001")
    assert restarted.status == OperationStatus.SUCCEEDED
    assert restarted.result["restart"] is True
    assert restarted.result["pid"] != first_pid
    assert len(launcher.calls) == 3


def test_launch_uses_array_safe_environment_and_hidden_windows_flags(
    managed_runtime_environment, monkeypatch
):
    environment = managed_runtime_environment
    revision = apply_configuration(environment)
    service, _port, launcher, _identity = fake_service(environment)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "synthetic-secret-must-not-inherit")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-api-key-must-not-inherit")
    monkeypatch.setenv("HTTP_PROXY", "http://user:password@127.0.0.1:9")
    execute(service, environment["database"], "start", revision, "safe-launch-key-01")
    arguments, options = launcher.calls[0]
    assert isinstance(arguments, list)
    assert arguments[1] == "-config"
    assert options["shell"] is False
    assert options["cwd"] == str(environment["version_store"].current().executable.parent)
    assert "TELEGRAM_BOT_TOKEN" not in options["env"]
    assert "OPENAI_API_KEY" not in options["env"]
    assert "HTTP_PROXY" not in options["env"]
    assert "PATH" not in options["env"]
    if os.name == "nt":
        assert options["creationflags"] & WINDOWS_CREATE_NO_WINDOW
        assert options["creationflags"] & WINDOWS_CREATE_NEW_PROCESS_GROUP


def test_startup_timeout_stops_only_launched_identity(managed_runtime_environment):
    environment = managed_runtime_environment
    revision = apply_configuration(environment)
    service, port, launcher, _identity = fake_service(environment, claim_port=False)
    operation = execute(service, environment["database"], "start", revision, "timeout-start-key")
    assert operation.status == OperationStatus.FAILED
    assert operation.error and operation.error.code == "MANAGED_PROCESS_STARTUP_TIMEOUT"
    process = next(iter(launcher.processes.values()))
    assert not process.running
    assert port.owner_pid is None


def test_port_conflict_before_and_after_launch_never_kills_external_owner(
    managed_runtime_environment,
):
    environment = managed_runtime_environment
    revision = apply_configuration(environment)
    service, port, launcher, _identity = fake_service(environment)
    port.owner_pid = 49999
    blocked = execute(service, environment["database"], "start", revision, "port-preflight-key")
    assert blocked.status == OperationStatus.FAILED
    assert blocked.error and blocked.error.code == "MANAGED_PORT_CONFLICT"
    assert not launcher.calls
    assert port.owner_pid == 49999

    port.owner_pid = None
    service, port, launcher, _identity = fake_service(environment, conflicting_pid=49998)
    wrong_owner = execute(
        service, environment["database"], "start", revision, "port-postlaunch-key"
    )
    assert wrong_owner.status == OperationStatus.FAILED
    assert wrong_owner.error and wrong_owner.error.code == "MANAGED_PORT_OWNED_BY_OTHER_PID"
    assert port.owner_pid == 49998
    assert not next(iter(launcher.processes.values())).running


def test_pid_reuse_and_identity_mismatch_refuse_stop(managed_runtime_environment):
    environment = managed_runtime_environment
    revision = apply_configuration(environment)
    service, _port, launcher, identity = fake_service(environment)
    started = execute(service, environment["database"], "start", revision, "identity-start-key")
    process = launcher.processes[started.result["pid"]]
    identity.override = IdentityVerification(
        status="pid_reused",
        checks={"process_exists": True, "create_time": False},
        diagnostic_code="MANAGED_PROCESS_PID_REUSED",
    )
    rejected = execute(service, environment["database"], "stop", revision, "pid-reuse-stop-key")
    assert rejected.status == OperationStatus.FAILED
    assert rejected.error and rejected.error.code == "MANAGED_PROCESS_PID_REUSED"
    assert process.running

    identity.override = IdentityVerification(
        status="mismatch",
        checks={"executable_sha256": False},
        diagnostic_code="MANAGED_PROCESS_EXECUTABLE_INTEGRITY_FAILURE",
    )
    rejected_sha = execute(service, environment["database"], "stop", revision, "sha-mismatch-stop")
    assert rejected_sha.error
    assert rejected_sha.error.code == "MANAGED_PROCESS_EXECUTABLE_INTEGRITY_FAILURE"
    assert process.running


def test_external_owner_and_revision_conflicts_block_start(managed_runtime_environment):
    environment = managed_runtime_environment
    revision = apply_configuration(environment)
    service, _port, launcher, _identity = fake_service(environment)
    wrong_revision = execute(
        service, environment["database"], "start", revision + 1, "wrong-revision-key"
    )
    assert wrong_revision.status == OperationStatus.FAILED
    assert wrong_revision.error and wrong_revision.error.code == "CONFIGURATION_REVISION_CONFLICT"
    assert not launcher.calls

    with environment["database"].session() as session:
        record = session.get(ManagedProcessRecord, "cc-connect")
        assert record is not None
        record.lifecycle_owner = "external"
    external = execute(service, environment["database"], "start", revision, "external-owner-key")
    assert external.status == OperationStatus.FAILED
    assert external.error and external.error.code == "LIFECYCLE_OWNER_NOT_PRODUCT"
    assert not launcher.calls


def test_crash_and_control_plane_restart_reconcile_truthfully(managed_runtime_environment):
    environment = managed_runtime_environment
    revision = apply_configuration(environment)
    service, port, launcher, identity = fake_service(environment)
    started = execute(service, environment["database"], "start", revision, "reconcile-start-key")
    pid = started.result["pid"]

    restarted_service = ManagedProcessService(
        environment["database"],
        environment["installer"].layout,
        environment["configuration"],
        version_store=environment["version_store"],
        identity_inspector=identity,
        port_inspector=port,
        launcher=launcher,
        process_factory=launcher.process_factory,
        external_detector=lambda: False,
        stable_window_seconds=0.01,
    )
    recovered = restarted_service.status()
    assert recovered.observed_state == "running_partial"
    assert recovered.pid == pid
    assert recovered.identity_verification
    assert recovered.identity_verification.status == "verified"

    launcher.processes[pid].force_exit(7)
    crashed = restarted_service.status()
    assert crashed.observed_state == "crashed"
    assert crashed.pid is None
    assert crashed.health.overall == "unhealthy"


def test_forced_termination_result_is_explicit(managed_runtime_environment, monkeypatch):
    environment = managed_runtime_environment
    revision = apply_configuration(environment)
    service, port, launcher, _identity = fake_service(environment)
    started = execute(service, environment["database"], "start", revision, "force-start-key-01")
    pid = started.result["pid"]

    def forced(identity):
        launcher.processes[identity.pid].force_exit(-9)
        port.owner_pid = None
        return True

    monkeypatch.setattr(service, "_terminate_verified_tree", forced)
    stopped = execute(service, environment["database"], "stop", revision, "force-stop-key-001")
    assert stopped.status == OperationStatus.SUCCEEDED
    assert stopped.result["forced_termination"] is True
    assert not launcher.processes[pid].running

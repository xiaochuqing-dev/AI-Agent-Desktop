from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from control_plane.application.operation_store import OperationStore
from control_plane.domain.models import OperationStatus, ResourceRef
from control_plane.infrastructure.config import Settings
from control_plane.operations import OperationExecutor, RecoveryDecision
from control_plane.persistence.models import OperationJobRecord
from control_plane.persistence.session import Database


def create_operation(database: Database, key: str, *, target: str = "cc-connect"):
    idempotency_key = key.ljust(16, "x")
    with database.session() as session:
        operation, _ = OperationStore(session).create(
            kind="test_job",
            target_ref=ResourceRef(kind="component", id=target),
            idempotency_key=idempotency_key,
            method="POST",
            resource="/test",
            body=key.encode(),
        )
    return operation


def wait_terminal(database: Database, operation_id: str, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with database.session() as session:
            operation = OperationStore(session).get(operation_id)
        if operation and operation.status in {
            OperationStatus.SUCCEEDED,
            OperationStatus.FAILED,
            OperationStatus.CANCELED,
        }:
            return operation
        time.sleep(0.01)
    raise AssertionError("operation did not reach a terminal state")


def test_executor_persists_and_executes_bounded_queue(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    executed: list[str] = []
    executor = OperationExecutor(database, worker_count=1, queue_capacity=1)
    executor.register(
        "test_job", lambda context: executed.append(context.operation_id) or {"ok": True}
    )
    executor.start()
    operations = [create_operation(database, f"queue-key-{index:02d}") for index in range(4)]
    for operation in operations:
        assert executor.submit(
            operation_id=operation.operation_id,
            component_id="cc-connect",
            kind="test_job",
        )
    for operation in operations:
        completed = wait_terminal(database, operation.operation_id)
        assert completed.status == OperationStatus.SUCCEEDED
        assert completed.result == {"ok": True}
    assert set(executed) == {operation.operation_id for operation in operations}
    assert executor.shutdown()


def test_executor_serializes_same_component_with_multiple_workers(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    guard = threading.Lock()
    active = 0
    max_active = 0

    def handler(_context):
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with guard:
            active -= 1
        return {"serialized": True}

    executor = OperationExecutor(database, worker_count=2, queue_capacity=4)
    executor.register("test_job", handler)
    executor.start()
    first = create_operation(database, "mutex-key-0000001")
    second = create_operation(database, "mutex-key-0000002")
    for operation in (first, second):
        executor.submit(
            operation_id=operation.operation_id,
            component_id="cc-connect",
            kind="test_job",
        )
    wait_terminal(database, first.operation_id)
    wait_terminal(database, second.operation_id)
    assert max_active == 1
    assert executor.shutdown()


def test_queued_cancellation_never_calls_handler(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    first_started = threading.Event()
    release_first = threading.Event()
    executed: list[str] = []

    def handler(context):
        executed.append(context.operation_id)
        if len(executed) == 1:
            first_started.set()
            assert release_first.wait(2)
        return {}

    executor = OperationExecutor(database, worker_count=1, queue_capacity=2)
    executor.register("test_job", handler)
    executor.start()
    first = create_operation(database, "cancel-queue-key-01")
    second = create_operation(database, "cancel-queue-key-02")
    executor.submit(operation_id=first.operation_id, component_id="cc-connect", kind="test_job")
    executor.submit(operation_id=second.operation_id, component_id="cc-connect", kind="test_job")
    assert first_started.wait(2)
    with database.session() as session:
        OperationStore(session).transition(
            second.operation_id,
            status=OperationStatus.CANCEL_REQUESTED,
            phase="cancel_requested",
        )
    release_first.set()
    assert wait_terminal(database, second.operation_id).status == OperationStatus.CANCELED
    assert executed == [first.operation_id]
    assert executor.shutdown()


def test_executor_recovery_probes_then_requeues_interrupted_job(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    operation = create_operation(database, "recovery-key-00001")
    now = datetime.now(UTC)
    with database.session() as session:
        OperationStore(session).transition(
            operation.operation_id,
            status=OperationStatus.RUNNING,
            phase="interrupted",
        )
        session.add(
            OperationJobRecord(
                operation_id=operation.operation_id,
                component_id="cc-connect",
                kind="test_job",
                payload_json="{}",
                state="running",
                attempts=1,
                created_at=now,
                updated_at=now,
            )
        )
    probes: list[str] = []
    executor = OperationExecutor(database, worker_count=1, queue_capacity=2)
    executor.register(
        "test_job",
        lambda _context: {"recovered": True},
        recovery_probe=lambda operation_id, _payload: (
            probes.append(operation_id) or RecoveryDecision.requeue()
        ),
    )
    executor.start()
    completed = wait_terminal(database, operation.operation_id)
    assert completed.status == OperationStatus.SUCCEEDED
    assert completed.result == {"recovered": True}
    assert probes == [operation.operation_id]
    assert executor.shutdown()


def test_terminal_job_is_not_repeated_on_restart(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    operation = create_operation(database, "terminal-key-00001")
    now = datetime.now(UTC)
    with database.session() as session:
        OperationStore(session).transition(
            operation.operation_id,
            status=OperationStatus.SUCCEEDED,
            phase="completed",
            result={"original": True},
        )
        session.add(
            OperationJobRecord(
                operation_id=operation.operation_id,
                component_id="cc-connect",
                kind="test_job",
                payload_json="{}",
                state="running",
                attempts=1,
                created_at=now,
                updated_at=now,
            )
        )
    calls = 0

    def handler(_context):
        nonlocal calls
        calls += 1
        return {}

    executor = OperationExecutor(database)
    executor.register("test_job", handler)
    executor.start()
    time.sleep(0.05)
    with database.session() as session:
        persisted = OperationStore(session).get(operation.operation_id)
        job = session.get(OperationJobRecord, operation.operation_id)
    assert persisted and persisted.result == {"original": True}
    assert job and job.state == "succeeded"
    assert calls == 0
    assert executor.shutdown()


def test_shutdown_timeout_is_reported_and_worker_honors_shutdown_event(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    started = threading.Event()

    def handler(context):
        started.set()
        assert context.shutdown_event.wait(2)
        return {"shutdown_seen": True}

    executor = OperationExecutor(
        database,
        worker_count=1,
        queue_capacity=1,
        shutdown_timeout_seconds=0.01,
    )
    executor.register("test_job", handler)
    executor.start()
    operation = create_operation(database, "shutdown-key-0001")
    executor.submit(operation_id=operation.operation_id, component_id="cc-connect", kind="test_job")
    assert started.wait(2)
    assert executor.shutdown() is False
    deadline = time.monotonic() + 2
    while any(thread.is_alive() for thread in executor._threads) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not any(thread.is_alive() for thread in executor._threads)

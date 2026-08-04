from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select

from ..application.operation_store import OperationStore
from ..domain.models import OperationStatus, UserFacingError
from ..persistence.models import OperationEventRecord, OperationJobRecord, OperationRecord
from ..persistence.session import Database

OperationHandler = Callable[["ExecutionContext"], dict[str, Any] | None]
RecoveryProbe = Callable[[str, dict[str, Any]], "RecoveryDecision"]


def utcnow() -> datetime:
    return datetime.now(UTC)


class RecoveryAction(StrEnum):
    COMPLETE = "complete"
    REQUEUE = "requeue"
    FAIL = "fail"


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    result: dict[str, Any] | None = None
    error: UserFacingError | None = None

    @classmethod
    def complete(cls, result: dict[str, Any] | None = None) -> RecoveryDecision:
        return cls(RecoveryAction.COMPLETE, result=result)

    @classmethod
    def requeue(cls) -> RecoveryDecision:
        return cls(RecoveryAction.REQUEUE)

    @classmethod
    def fail(
        cls,
        *,
        code: str = "OPERATION_RECOVERY_UNSAFE",
        message: str = "The interrupted operation cannot be resumed safely.",
        recovery_actions: list[str] | None = None,
    ) -> RecoveryDecision:
        return cls(
            RecoveryAction.FAIL,
            error=UserFacingError(
                code=code,
                message=message,
                retryable=True,
                recovery_actions=recovery_actions or ["inspect_state", "retry_after_review"],
            ),
        )


class OperationExecutionError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        recovery_actions: list[str] | None = None,
    ) -> None:
        self.error = UserFacingError(
            code=code,
            message=message,
            retryable=retryable,
            recovery_actions=recovery_actions or [],
        )
        super().__init__(message)


@dataclass(frozen=True)
class ExecutionContext:
    operation_id: str
    component_id: str
    kind: str
    payload: dict[str, Any]
    database: Database
    shutdown_event: threading.Event

    def cancellation_requested(self) -> bool:
        with self.database.session() as session:
            operation = OperationStore(session).get(self.operation_id)
        return operation is not None and operation.status == OperationStatus.CANCEL_REQUESTED

    def safe_checkpoint(self) -> None:
        if self.cancellation_requested():
            raise OperationExecutionError(
                "OPERATION_CANCELED",
                "Operation was canceled at a safe checkpoint.",
            )
        if self.shutdown_event.is_set():
            raise OperationExecutionError(
                "OPERATION_SHUTDOWN_INTERRUPTED",
                "Control Plane shutdown interrupted the operation at a safe checkpoint.",
                retryable=True,
                recovery_actions=["restart_control_plane"],
            )


@dataclass(frozen=True)
class _Registration:
    handler: OperationHandler
    recovery_probe: RecoveryProbe


class OperationExecutor:
    """Bounded, persisted, single-process executor for Control Plane operations."""

    def __init__(
        self,
        database: Database,
        *,
        worker_count: int = 2,
        queue_capacity: int = 64,
        shutdown_timeout_seconds: float = 10.0,
    ) -> None:
        if worker_count < 1 or queue_capacity < 1:
            raise ValueError("worker_count and queue_capacity must be positive")
        self.database = database
        self.worker_count = worker_count
        self.shutdown_timeout_seconds = shutdown_timeout_seconds
        self._queue: queue.Queue[str] = queue.Queue(maxsize=queue_capacity)
        self._registrations: dict[str, _Registration] = {}
        self._component_locks: dict[str, threading.Lock] = {}
        self._component_locks_guard = threading.Lock()
        self._enqueued: set[str] = set()
        self._enqueued_guard = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._started = False
        self._accepting = False
        self._shutdown = threading.Event()

    def register(
        self,
        kind: str,
        handler: OperationHandler,
        *,
        recovery_probe: RecoveryProbe | None = None,
    ) -> None:
        if self._started:
            raise RuntimeError("handlers must be registered before executor start")
        if kind in self._registrations:
            raise ValueError(f"operation handler already registered: {kind}")
        self._registrations[kind] = _Registration(
            handler=handler,
            recovery_probe=recovery_probe or self._default_recovery_probe,
        )

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._accepting = True
        self._recover_persisted_jobs()
        for index in range(self.worker_count):
            thread = threading.Thread(
                target=self._worker,
                name=f"control-plane-operation-{index + 1}",
                daemon=False,
            )
            thread.start()
            self._threads.append(thread)
        self._fill_queue()

    def submit(
        self,
        *,
        operation_id: str,
        component_id: str,
        kind: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        if not self._started or not self._accepting:
            raise RuntimeError("operation executor is not accepting work")
        if kind not in self._registrations:
            raise ValueError(f"operation handler is not registered: {kind}")
        now = utcnow()
        created = False
        with self.database.session() as session:
            operation = session.get(OperationRecord, operation_id)
            if operation is None:
                raise ValueError(f"operation does not exist: {operation_id}")
            existing = session.get(OperationJobRecord, operation_id)
            if existing is None:
                session.add(
                    OperationJobRecord(
                        operation_id=operation_id,
                        component_id=component_id,
                        kind=kind,
                        payload_json=json.dumps(payload or {}, sort_keys=True),
                        state="queued",
                        attempts=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
                created = True
            elif existing.kind != kind or existing.component_id != component_id:
                raise ValueError("persisted job identity does not match submission")
        self._fill_queue()
        return created

    def shutdown(self, timeout_seconds: float | None = None) -> bool:
        if not self._started:
            return True
        self._accepting = False
        timeout = self.shutdown_timeout_seconds if timeout_seconds is None else timeout_seconds
        deadline = time.monotonic() + max(timeout, 0.0)
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        drained = self._queue.unfinished_tasks == 0
        self._shutdown.set()
        for thread in self._threads:
            remaining = max(0.0, deadline - time.monotonic())
            thread.join(remaining)
        stopped = all(not thread.is_alive() for thread in self._threads)
        self._started = False
        return drained and stopped

    def _worker(self) -> None:
        while not self._shutdown.is_set():
            try:
                operation_id = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._execute(operation_id)
            finally:
                with self._enqueued_guard:
                    self._enqueued.discard(operation_id)
                self._queue.task_done()
                self._fill_queue()

    def _execute(self, operation_id: str) -> None:
        with self.database.session() as session:
            job = session.get(OperationJobRecord, operation_id)
            operation = OperationStore(session).get(operation_id)
            if job is None or operation is None:
                return
            if operation.status in {
                OperationStatus.SUCCEEDED,
                OperationStatus.FAILED,
                OperationStatus.CANCELED,
            }:
                job.state = operation.status.value
                job.updated_at = utcnow()
                return
            component_id = job.component_id
        component_lock = self._component_lock(component_id)
        with component_lock:
            self._execute_locked(operation_id)

    def _execute_locked(self, operation_id: str) -> None:
        with self.database.session() as session:
            job = session.get(OperationJobRecord, operation_id)
            store = OperationStore(session)
            operation = store.get(operation_id)
            if job is None or operation is None:
                return
            if operation.status in {
                OperationStatus.SUCCEEDED,
                OperationStatus.FAILED,
                OperationStatus.CANCELED,
            }:
                job.state = operation.status.value
                job.updated_at = utcnow()
                return
            if operation.status == OperationStatus.CANCEL_REQUESTED:
                store.transition(
                    operation_id,
                    status=OperationStatus.CANCELED,
                    phase="canceled_before_dispatch",
                    message="Operation was canceled before execution.",
                )
                job.state = "canceled"
                job.updated_at = utcnow()
                self._audit(session, operation_id, "operation.canceled", "canceled_before_dispatch")
                return
            registration = self._registrations.get(job.kind)
            if registration is None:
                self._fail_unregistered(session, store, job)
                return
            job.state = "running"
            job.attempts += 1
            job.updated_at = utcnow()
            store.transition(
                operation_id,
                status=OperationStatus.RUNNING,
                phase="dispatching",
                message="Operation dispatched by the persisted executor.",
            )
            self._audit(session, operation_id, "operation.dispatched", "dispatching")
            context = ExecutionContext(
                operation_id=operation_id,
                component_id=job.component_id,
                kind=job.kind,
                payload=json.loads(job.payload_json),
                database=self.database,
                shutdown_event=self._shutdown,
            )
        try:
            result = registration.handler(context)
            self._finish_after_handler(operation_id, result)
        except OperationExecutionError as exc:
            self._fail(operation_id, exc.error)
        except Exception as exc:  # pragma: no cover - defensive boundary
            self._fail(
                operation_id,
                UserFacingError(
                    code="OPERATION_EXECUTION_FAILED",
                    message=f"Operation handler failed: {type(exc).__name__}",
                    retryable=True,
                    recovery_actions=["inspect_diagnostic", "retry_after_review"],
                ),
            )

    def _finish_after_handler(self, operation_id: str, result: dict[str, Any] | None) -> None:
        with self.database.session() as session:
            store = OperationStore(session)
            operation = store.get(operation_id)
            job = session.get(OperationJobRecord, operation_id)
            if operation is None or job is None:
                return
            if operation.status == OperationStatus.CANCEL_REQUESTED:
                operation = store.transition(
                    operation_id,
                    status=OperationStatus.CANCELED,
                    phase="canceled",
                    message="Operation stopped at a safe cancellation point.",
                )
            elif operation.status not in {
                OperationStatus.SUCCEEDED,
                OperationStatus.FAILED,
                OperationStatus.CANCELED,
            }:
                operation = store.transition(
                    operation_id,
                    status=OperationStatus.SUCCEEDED,
                    phase="completed",
                    message="Operation completed.",
                    result=result or {},
                )
            assert operation is not None
            job.state = operation.status.value
            job.updated_at = utcnow()
            self._audit(
                session,
                operation_id,
                f"operation.{operation.status.value}",
                operation.progress.phase,
            )

    def _fail(self, operation_id: str, error: UserFacingError) -> None:
        with self.database.session() as session:
            store = OperationStore(session)
            job = session.get(OperationJobRecord, operation_id)
            operation = store.get(operation_id)
            if job is None or operation is None:
                return
            if operation.status not in {
                OperationStatus.SUCCEEDED,
                OperationStatus.FAILED,
                OperationStatus.CANCELED,
            }:
                store.transition(
                    operation_id,
                    status=OperationStatus.FAILED,
                    phase="failed",
                    message=error.message,
                    error=error,
                )
            job.state = "failed"
            job.updated_at = utcnow()
            self._audit(session, operation_id, "operation.failed", "failed")

    def _recover_persisted_jobs(self) -> None:
        with self.database.session() as session:
            jobs = list(
                session.scalars(
                    select(OperationJobRecord).where(
                        OperationJobRecord.state.in_(["queued", "running"])
                    )
                )
            )
            tracked = {job.operation_id for job in jobs}
        for job in jobs:
            self._recover_job(job.operation_id)
        with self.database.session() as session:
            untracked = list(
                session.scalars(
                    select(OperationRecord).where(
                        OperationRecord.status.in_(["queued", "running", "cancel_requested"]),
                        ~OperationRecord.operation_id.in_(tracked),
                    )
                )
            )
            store = OperationStore(session)
            for record in untracked:
                store.transition(
                    record.operation_id,
                    status=OperationStatus.FAILED,
                    phase="recovery_untracked",
                    message="No persisted executor job exists for the interrupted operation.",
                    error=UserFacingError(
                        code="OPERATION_RECOVERY_UNTRACKED",
                        message="Interrupted operation has no recoverable executor record.",
                        retryable=True,
                        recovery_actions=["reprobe", "retry_after_review"],
                    ),
                )

    def _recover_job(self, operation_id: str) -> None:
        with self.database.session() as session:
            job = session.get(OperationJobRecord, operation_id)
            operation = OperationStore(session).get(operation_id)
            if job is None or operation is None:
                return
            if operation.status in {
                OperationStatus.SUCCEEDED,
                OperationStatus.FAILED,
                OperationStatus.CANCELED,
            }:
                job.state = operation.status.value
                job.updated_at = utcnow()
                return
            registration = self._registrations.get(job.kind)
            payload = json.loads(job.payload_json)
        decision = (
            registration.recovery_probe(operation_id, payload)
            if registration is not None
            else RecoveryDecision.fail(code="OPERATION_HANDLER_UNAVAILABLE")
        )
        with self.database.session() as session:
            job = session.get(OperationJobRecord, operation_id)
            store = OperationStore(session)
            if job is None:
                return
            if decision.action == RecoveryAction.COMPLETE:
                store.transition(
                    operation_id,
                    status=OperationStatus.SUCCEEDED,
                    phase="recovered_complete",
                    message="On-disk state proves the interrupted operation completed.",
                    result=decision.result or {},
                )
                job.state = "succeeded"
            elif decision.action == RecoveryAction.REQUEUE:
                store.transition(
                    operation_id,
                    status=OperationStatus.QUEUED,
                    phase="recovered_queued",
                    message="Recovery probe found a safe retry point.",
                )
                job.state = "queued"
            else:
                error = decision.error or RecoveryDecision.fail().error
                assert error is not None
                store.transition(
                    operation_id,
                    status=OperationStatus.FAILED,
                    phase="recovery_failed",
                    message=error.message,
                    error=error,
                )
                job.state = "failed"
            job.updated_at = utcnow()
            self._audit(
                session,
                operation_id,
                f"operation.recovery.{decision.action.value}",
                f"recovery_{decision.action.value}",
            )

    def _fill_queue(self) -> None:
        if not self._started or self._shutdown.is_set():
            return
        with self.database.session() as session:
            operation_ids = list(
                session.scalars(
                    select(OperationJobRecord.operation_id)
                    .where(OperationJobRecord.state == "queued")
                    .order_by(OperationJobRecord.created_at)
                )
            )
        with self._enqueued_guard:
            for operation_id in operation_ids:
                if operation_id in self._enqueued:
                    continue
                try:
                    self._queue.put_nowait(operation_id)
                except queue.Full:
                    break
                self._enqueued.add(operation_id)

    def _component_lock(self, component_id: str) -> threading.Lock:
        with self._component_locks_guard:
            return self._component_locks.setdefault(component_id, threading.Lock())

    def _fail_unregistered(self, session, store: OperationStore, job: OperationJobRecord) -> None:
        error = UserFacingError(
            code="OPERATION_HANDLER_UNAVAILABLE",
            message="No executor handler is registered for this operation kind.",
            retryable=True,
            recovery_actions=["restart_control_plane", "inspect_diagnostic"],
        )
        store.transition(
            job.operation_id,
            status=OperationStatus.FAILED,
            phase="handler_unavailable",
            message=error.message,
            error=error,
        )
        job.state = "failed"
        job.updated_at = utcnow()
        self._audit(session, job.operation_id, "operation.failed", "handler_unavailable")

    @staticmethod
    def _default_recovery_probe(_operation_id: str, _payload: dict[str, Any]) -> RecoveryDecision:
        return RecoveryDecision.fail()

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

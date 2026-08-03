# Operation 存储:状态机、幂等、重启恢复。领域 Operation 与 ORM 记录互转。
# 重启时未终止 Operation(queued/running/cancel_requested)转 failed + Diagnostic,禁止自动重放。
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.models import (
    Operation,
    OperationProgress,
    OperationStatus,
    ResourceRef,
    UserFacingError,
)
from ..persistence.models import IdempotencyRecord, OperationRecord


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    # 不用 Math.random / uuid4 随机部分做稳定 ID;component_id 由 Adapter 稳定生成。
    # operation_id 用 uuid4 保证全局唯一(非稳定语义字段)。
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def body_digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class OperationStore:
    def __init__(self, session: Session) -> None:
        self.s = session

    def create(
        self,
        *,
        kind: str,
        target_ref: ResourceRef,
        idempotency_key: str,
        method: str,
        resource: str,
        body: bytes,
    ) -> tuple[Operation, bool]:
        # 幂等检查:同 key 同摘要返回原 Operation;同 key 不同摘要返回冲突(以异常表达)。
        existing = self.s.get(IdempotencyRecord, idempotency_key)
        if existing is not None:
            if existing.body_digest != body_digest(body):
                raise IdempotencyKeyReuse(idempotency_key)
            op = self._load(existing.operation_id)
            if op is None:
                raise IdempotencyKeyReuse(idempotency_key)
            return op, True  # 复用原响应

        op_id = new_id("op")
        now = utcnow()
        op = Operation(
            operation_id=op_id,
            kind=kind,
            target_ref=target_ref,
            status=OperationStatus.QUEUED,
            progress=OperationProgress(
                phase="queued",
                message="",
                completed_units=0,
                total_units=None,
                point_of_no_return=False,
            ),
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
        )
        self._persist(op)
        self.s.add(
            IdempotencyRecord(
                idempotency_key=idempotency_key,
                method=method,
                resource=resource,
                body_digest=body_digest(body),
                operation_id=op_id,
                response_status=202,
                created_at=now,
            )
        )
        return op, False

    def _persist(self, op: Operation) -> None:
        rec = OperationRecord(
            operation_id=op.operation_id,
            kind=op.kind,
            target_kind=op.target_ref.kind,
            target_id=op.target_ref.id,
            status=op.status.value,
            progress_phase=op.progress.phase,
            progress_message=op.progress.message,
            completed_units=op.progress.completed_units,
            total_units=op.progress.total_units,
            point_of_no_return=1 if op.progress.point_of_no_return else 0,
            result_json=op.model_dump_json() if op.result else None,
            error_json=op.error.model_dump_json() if op.error else None,
            idempotency_key=op.idempotency_key,
            created_at=op.created_at,
            updated_at=op.updated_at,
            completed_at=op.completed_at,
        )
        self.s.merge(rec)

    def _load(self, operation_id: str) -> Operation | None:
        rec = self.s.get(OperationRecord, operation_id)
        if rec is None:
            return None
        return self._from_record(rec)

    def _from_record(self, rec: OperationRecord) -> Operation:
        result = json.loads(rec.result_json) if rec.result_json else None
        error = UserFacingError.model_validate_json(rec.error_json) if rec.error_json else None
        return Operation(
            operation_id=rec.operation_id,
            kind=rec.kind,
            target_ref=ResourceRef(kind=rec.target_kind, id=rec.target_id),
            status=OperationStatus(rec.status),
            progress=OperationProgress(
                phase=rec.progress_phase,
                message=rec.progress_message or "",
                completed_units=rec.completed_units or 0,
                total_units=rec.total_units,
                point_of_no_return=bool(rec.point_of_no_return),
            ),
            result=result,
            error=error,
            idempotency_key=rec.idempotency_key,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
            completed_at=rec.completed_at,
        )

    def get(self, operation_id: str) -> Operation | None:
        return self._load(operation_id)

    def list_operations(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        target_id: str | None = None,
        limit: int = 50,
    ) -> list[Operation]:
        stmt = select(OperationRecord).order_by(OperationRecord.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(OperationRecord.status == status)
        if kind:
            stmt = stmt.where(OperationRecord.kind == kind)
        if target_id:
            stmt = stmt.where(OperationRecord.target_id == target_id)
        return [self._from_record(r) for r in self.s.scalars(stmt)]

    def transition(
        self,
        operation_id: str,
        *,
        status: OperationStatus,
        phase: str | None = None,
        message: str | None = None,
        completed_units: int | None = None,
        total_units: int | None = None,
        result: dict | None = None,
        error: UserFacingError | None = None,
    ) -> Operation | None:
        rec = self.s.get(OperationRecord, operation_id)
        if rec is None:
            return None
        now = utcnow()
        rec.status = status.value
        rec.updated_at = now
        if phase is not None:
            rec.progress_phase = phase
        if message is not None:
            rec.progress_message = message
        if completed_units is not None:
            rec.completed_units = completed_units
        if total_units is not None:
            rec.total_units = total_units
        if result is not None:
            rec.result_json = json.dumps(result)
        if error is not None:
            rec.error_json = error.model_dump_json()
        if status in (OperationStatus.SUCCEEDED, OperationStatus.FAILED, OperationStatus.CANCELED):
            rec.completed_at = now
        return self._from_record(rec)

    def recover_on_startup(self) -> list[str]:
        # 重启恢复:未终止 Operation 转 failed,生成 diagnostic,禁止自动重放未知副作用。
        stmt = select(OperationRecord).where(
            OperationRecord.status.in_(["queued", "running", "cancel_requested"])
        )
        recovered: list[str] = []
        now = utcnow()
        for rec in self.s.scalars(stmt):
            rec.status = OperationStatus.FAILED.value
            rec.updated_at = now
            rec.completed_at = now
            rec.error_json = UserFacingError(
                code="OPERATION_RECOVERY_UNKNOWN",
                message="Control Plane restarted before the operation completed; side effect state is unknown.",
                retryable=True,
                recovery_actions=["reprobe", "retry_after_review"],
            ).model_dump_json()
            recovered.append(rec.operation_id)
        return recovered


class IdempotencyKeyReuse(Exception):
    # 同 key 不同摘要:对应 409 IDEMPOTENCY_KEY_REUSE
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"idempotency key reuse: {key}")

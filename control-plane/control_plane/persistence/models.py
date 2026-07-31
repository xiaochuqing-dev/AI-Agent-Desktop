# ORM 模型:Operation、幂等记录、Component 状态快照、Diagnostic、事件游标。
# 使用 SQLAlchemy 2.0 Mapped 注解,满足 mypy 类型检查。
# 不存明文 Secret;不存 Authorization;不存聊天正文。
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OperationRecord(Base):
    __tablename__ = "operations"
    operation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(128))
    target_kind: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32))  # queued/running/cancel_requested/succeeded/failed/canceled
    progress_phase: Mapped[str] = mapped_column(String(128))
    progress_message: Mapped[str] = mapped_column(Text, default="")
    completed_units: Mapped[int] = mapped_column(Integer, default=0)
    total_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    point_of_no_return: Mapped[int] = mapped_column(Integer, default=0)  # 0/1
    # result 与 error 以 JSON 文本存储,序列化前已脱敏
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(256), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency"
    idempotency_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    method: Mapped[str] = mapped_column(String(16))
    resource: Mapped[str] = mapped_column(String(256))
    body_digest: Mapped[str] = mapped_column(String(128))  # 规范化 body 摘要
    operation_id: Mapped[str] = mapped_column(String(128), index=True)
    response_status: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class DiagnosticRecord(Base):
    __tablename__ = "diagnostics"
    diagnostic_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    severity: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(String(128))
    summary: Mapped[str] = mapped_column(Text)
    user_message: Mapped[str] = mapped_column(Text)
    suggested_actions_json: Mapped[str] = mapped_column(Text, default="[]")
    technical_details_json: Mapped[str] = mapped_column(Text, default="{}")  # 已脱敏
    redaction_applied: Mapped[int] = mapped_column(Integer, default=1)  # 恒 1
    created_at: Mapped[datetime] = mapped_column(DateTime)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    operation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class EventCursorRecord(Base):
    __tablename__ = "event_cursors"
    epoch: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ComponentStateRecord(Base):
    __tablename__ = "component_state"
    component_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(256))
    version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 快照以 JSON 文本存储,序列化前已脱敏
    snapshot_json: Mapped[str] = mapped_column(Text)
    revision: Mapped[str] = mapped_column(String(128))
    observed_at: Mapped[datetime] = mapped_column(DateTime)

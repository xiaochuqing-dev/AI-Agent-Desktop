# ORM 模型:Operation、幂等记录、Component 状态快照、Diagnostic、事件游标。
# 不存明文 Secret;不存 Authorization;不存聊天正文。
from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class OperationRecord(Base):
    __tablename__ = "operations"
    operation_id = Column(String(128), primary_key=True)
    kind = Column(String(128), nullable=False)
    target_kind = Column(String(64), nullable=False)
    target_id = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False)  # queued/running/cancel_requested/succeeded/failed/canceled
    progress_phase = Column(String(128), nullable=False)
    progress_message = Column(Text, default="")
    completed_units = Column(Integer, default=0)
    total_units = Column(Integer, nullable=True)
    point_of_no_return = Column(Integer, default=0)  # 0/1
    # result 与 error 以 JSON 文本存储,序列化前已脱敏
    result_json = Column(Text, nullable=True)
    error_json = Column(Text, nullable=True)
    idempotency_key = Column(String(256), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency"
    idempotency_key = Column(String(256), primary_key=True)
    method = Column(String(16), nullable=False)
    resource = Column(String(256), nullable=False)
    body_digest = Column(String(128), nullable=False)  # 规范化 body 摘要
    operation_id = Column(String(128), nullable=False, index=True)
    response_status = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False)


class DiagnosticRecord(Base):
    __tablename__ = "diagnostics"
    diagnostic_id = Column(String(128), primary_key=True)
    severity = Column(String(16), nullable=False)
    code = Column(String(128), nullable=False)
    summary = Column(Text, nullable=False)
    user_message = Column(Text, nullable=False)
    suggested_actions_json = Column(Text, default="[]")
    technical_details_json = Column(Text, default="{}")  # 已脱敏
    redaction_applied = Column(Integer, default=1)  # 恒 1
    created_at = Column(DateTime, nullable=False)
    correlation_id = Column(String(128), nullable=False, index=True)
    operation_id = Column(String(128), nullable=True)
    target_kind = Column(String(64), nullable=True)
    target_id = Column(String(128), nullable=True)


class EventCursorRecord(Base):
    __tablename__ = "event_cursors"
    epoch = Column(String(128), primary_key=True)
    last_sequence = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False)


class ComponentStateRecord(Base):
    __tablename__ = "component_state"
    component_id = Column(String(128), primary_key=True)
    kind = Column(String(64), nullable=False)
    display_name = Column(String(256), nullable=False)
    version = Column(String(128), nullable=True)
    # 快照以 JSON 文本存储,序列化前已脱敏
    snapshot_json = Column(Text, nullable=False)
    revision = Column(String(128), nullable=False)
    observed_at = Column(DateTime, nullable=False)

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
    status: Mapped[str] = mapped_column(
        String(32)
    )  # queued/running/cancel_requested/succeeded/failed/canceled
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


class ArtifactRecord(Base):
    __tablename__ = "artifacts"
    artifact_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    component_id: Mapped[str] = mapped_column(String(128), index=True)
    source_ref: Mapped[str] = mapped_column(String(128))
    manifest_json: Mapped[str] = mapped_column(Text)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    artifact_size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class InstallPlanRecord(Base):
    __tablename__ = "install_plans"
    plan_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    component_id: Mapped[str] = mapped_column(String(128), index=True)
    artifact_id: Mapped[str] = mapped_column(String(128), index=True)
    plan_digest: Mapped[str] = mapped_column(String(71), unique=True)
    plan_json: Mapped[str] = mapped_column(Text)
    source_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class InstallSnapshotRecord(Base):
    __tablename__ = "install_snapshots"
    snapshot_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    component_id: Mapped[str] = mapped_column(String(128), index=True)
    snapshot_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class InstallRecordRecord(Base):
    __tablename__ = "install_records"
    install_record_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(128), index=True)
    component_id: Mapped[str] = mapped_column(String(128), index=True)
    artifact_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), index=True)
    relative_path: Mapped[str] = mapped_column(String(512))
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    management_owner: Mapped[str] = mapped_column(String(32))
    installed_at: Mapped[datetime] = mapped_column(DateTime)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ComponentVersionRecord(Base):
    __tablename__ = "component_versions"
    artifact_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    component_id: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[str] = mapped_column(String(128))
    relative_path: Mapped[str] = mapped_column(String(512))
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    artifact_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True)
    installed_at: Mapped[datetime] = mapped_column(DateTime)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PendingCleanupRecord(Base):
    __tablename__ = "pending_cleanup"
    cleanup_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(128), index=True)
    component_id: Mapped[str] = mapped_column(String(128), index=True)
    relative_path: Mapped[str] = mapped_column(String(512))
    reason_code: Mapped[str] = mapped_column(String(128))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class InstallationLeaseRecord(Base):
    __tablename__ = "installation_leases"
    component_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(128), unique=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime)


class OperationEventRecord(Base):
    __tablename__ = "operation_events"
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(String(128), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(128))
    phase: Mapped[str] = mapped_column(String(128))
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class OperationJobRecord(Base):
    __tablename__ = "operation_jobs"
    operation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    component_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(128), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    state: Mapped[str] = mapped_column(String(32), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ConfigurationPlanRecord(Base):
    __tablename__ = "configuration_plans"
    plan_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    component_id: Mapped[str] = mapped_column(String(128), index=True)
    artifact_id: Mapped[str] = mapped_column(String(128), index=True)
    plan_digest: Mapped[str] = mapped_column(String(71), unique=True)
    context_digest: Mapped[str] = mapped_column(String(71))
    plan_json: Mapped[str] = mapped_column(Text)
    target_payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    current_revision: Mapped[int] = mapped_column(Integer)
    target_revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ConfigurationRevisionRecord(Base):
    __tablename__ = "configuration_revisions"
    component_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String(128), index=True)
    product_instance_id: Mapped[str] = mapped_column(String(128), index=True)
    plan_id: Mapped[str] = mapped_column(String(128), index=True)
    configuration_digest: Mapped[str] = mapped_column(String(71))
    payload_json: Mapped[str] = mapped_column(Text)
    relative_path: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ConfigurationBackupRecord(Base):
    __tablename__ = "configuration_backups"
    backup_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    component_id: Mapped[str] = mapped_column(String(128), index=True)
    source_revision: Mapped[int] = mapped_column(Integer)
    operation_id: Mapped[str] = mapped_column(String(128), index=True)
    relative_path: Mapped[str] = mapped_column(String(512))
    configuration_digest: Mapped[str] = mapped_column(String(71))
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class PendingRepairRecord(Base):
    __tablename__ = "pending_repairs"
    repair_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    component_id: Mapped[str] = mapped_column(String(128), index=True)
    operation_id: Mapped[str] = mapped_column(String(128), index=True)
    reason_code: Mapped[str] = mapped_column(String(128))
    relative_path: Mapped[str] = mapped_column(String(512))
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class OwnershipPlanRecord(Base):
    __tablename__ = "ownership_plans"
    plan_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    component_id: Mapped[str] = mapped_column(String(128), index=True)
    artifact_id: Mapped[str] = mapped_column(String(128), index=True)
    plan_digest: Mapped[str] = mapped_column(String(71), unique=True)
    context_digest: Mapped[str] = mapped_column(String(71))
    plan_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ManagedProcessRecord(Base):
    __tablename__ = "managed_processes"
    component_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    product_instance_id: Mapped[str] = mapped_column(String(128), index=True)
    artifact_id: Mapped[str] = mapped_column(String(128), index=True)
    configuration_revision: Mapped[int] = mapped_column(Integer)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    process_create_time: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expected_state: Mapped[str] = mapped_column(String(32))
    observed_state: Mapped[str] = mapped_column(String(32), index=True)
    management_owner: Mapped[str] = mapped_column(String(32))
    lifecycle_owner: Mapped[str] = mapped_column(String(32))
    identity_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    health_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_operation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ProcessIdentityRecord(Base):
    __tablename__ = "process_identity_records"
    identity_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    component_id: Mapped[str] = mapped_column(String(128), index=True)
    operation_id: Mapped[str] = mapped_column(String(128), index=True)
    pid: Mapped[int] = mapped_column(Integer, index=True)
    process_create_time: Mapped[str] = mapped_column(String(64))
    identity_json: Mapped[str] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class PortOwnershipRecord(Base):
    __tablename__ = "port_ownership_records"
    ownership_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    component_id: Mapped[str] = mapped_column(String(128), index=True)
    operation_id: Mapped[str] = mapped_column(String(128), index=True)
    listen_host: Mapped[str] = mapped_column(String(64))
    listen_port: Mapped[int] = mapped_column(Integer, index=True)
    owner_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class LifecycleLeaseRecord(Base):
    __tablename__ = "lifecycle_leases"
    component_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(128), unique=True)
    owner: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(32))
    acquired_at: Mapped[datetime] = mapped_column(DateTime)


class LifecycleEventRecord(Base):
    __tablename__ = "lifecycle_events"
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component_id: Mapped[str] = mapped_column(String(128), index=True)
    operation_id: Mapped[str] = mapped_column(String(128), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(128))
    phase: Mapped[str] = mapped_column(String(128))
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ExternalToolCapabilityRecord(Base):
    __tablename__ = "external_tool_capabilities"
    provider_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    capabilities_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class UpdateAssessmentRecord(Base):
    __tablename__ = "update_assessments"
    assessment_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    component_id: Mapped[str] = mapped_column(String(128), index=True)
    current_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    assessment_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)

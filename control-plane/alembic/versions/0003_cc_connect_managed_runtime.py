from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_cc_connect_managed_runtime"
down_revision = "0002_cc_connect_installer"
branch_labels = None
depends_on = None


def _index(table: str, column: str) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "operation_jobs",
        sa.Column("operation_id", sa.String(128), primary_key=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(128), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in ("component_id", "kind", "state"):
        _index("operation_jobs", column)

    op.create_table(
        "configuration_plans",
        sa.Column("plan_id", sa.String(128), primary_key=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("artifact_id", sa.String(128), nullable=False),
        sa.Column("plan_digest", sa.String(71), nullable=False, unique=True),
        sa.Column("context_digest", sa.String(71), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("target_payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
    )
    for column in ("component_id", "artifact_id", "status"):
        _index("configuration_plans", column)

    op.create_table(
        "configuration_revisions",
        sa.Column("component_id", sa.String(128), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("artifact_id", sa.String(128), nullable=False),
        sa.Column("product_instance_id", sa.String(128), nullable=False),
        sa.Column("plan_id", sa.String(128), nullable=False),
        sa.Column("configuration_digest", sa.String(71), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("relative_path", sa.String(512), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("artifact_id", "product_instance_id", "plan_id", "status"):
        _index("configuration_revisions", column)

    op.create_table(
        "configuration_backups",
        sa.Column("backup_id", sa.String(128), primary_key=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("relative_path", sa.String(512), nullable=False),
        sa.Column("configuration_digest", sa.String(71), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("component_id", "operation_id", "status"):
        _index("configuration_backups", column)

    op.create_table(
        "pending_repairs",
        sa.Column("repair_id", sa.String(128), primary_key=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("reason_code", sa.String(128), nullable=False),
        sa.Column("relative_path", sa.String(512), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in ("component_id", "operation_id", "status"):
        _index("pending_repairs", column)

    op.create_table(
        "ownership_plans",
        sa.Column("plan_id", sa.String(128), primary_key=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("artifact_id", sa.String(128), nullable=False),
        sa.Column("plan_digest", sa.String(71), nullable=False, unique=True),
        sa.Column("context_digest", sa.String(71), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
    )
    for column in ("component_id", "artifact_id", "status"):
        _index("ownership_plans", column)

    op.create_table(
        "managed_processes",
        sa.Column("component_id", sa.String(128), primary_key=True),
        sa.Column("product_instance_id", sa.String(128), nullable=False),
        sa.Column("artifact_id", sa.String(128), nullable=False),
        sa.Column("configuration_revision", sa.Integer(), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("process_create_time", sa.String(64), nullable=True),
        sa.Column("expected_state", sa.String(32), nullable=False),
        sa.Column("observed_state", sa.String(32), nullable=False),
        sa.Column("management_owner", sa.String(32), nullable=False),
        sa.Column("lifecycle_owner", sa.String(32), nullable=False),
        sa.Column("identity_json", sa.Text(), nullable=True),
        sa.Column("health_json", sa.Text(), nullable=True),
        sa.Column("last_operation_id", sa.String(128), nullable=True),
        sa.Column("last_exit_code", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in ("product_instance_id", "artifact_id", "pid", "observed_state"):
        _index("managed_processes", column)

    op.create_table(
        "process_identity_records",
        sa.Column("identity_id", sa.String(128), primary_key=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("process_create_time", sa.String(64), nullable=False),
        sa.Column("identity_json", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("component_id", "operation_id", "pid", "verification_status"):
        _index("process_identity_records", column)

    op.create_table(
        "port_ownership_records",
        sa.Column("ownership_id", sa.String(128), primary_key=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("listen_host", sa.String(64), nullable=False),
        sa.Column("listen_port", sa.Integer(), nullable=False),
        sa.Column("owner_pid", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("component_id", "operation_id", "listen_port", "status"):
        _index("port_ownership_records", column)

    op.create_table(
        "lifecycle_leases",
        sa.Column("component_id", sa.String(128), primary_key=True),
        sa.Column("operation_id", sa.String(128), nullable=False, unique=True),
        sa.Column("owner", sa.String(32), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "lifecycle_events",
        sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("phase", sa.String(128), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("component_id", "operation_id"):
        _index("lifecycle_events", column)

    op.create_table(
        "external_tool_capabilities",
        sa.Column("provider_id", sa.String(128), primary_key=True),
        sa.Column("version", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("capabilities_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    _index("external_tool_capabilities", "status")

    op.create_table(
        "update_assessments",
        sa.Column("assessment_id", sa.String(128), primary_key=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("current_version", sa.String(128), nullable=True),
        sa.Column("target_version", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("assessment_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("component_id", "status"):
        _index("update_assessments", column)


def downgrade() -> None:
    for table in (
        "update_assessments",
        "external_tool_capabilities",
        "lifecycle_events",
        "lifecycle_leases",
        "port_ownership_records",
        "process_identity_records",
        "managed_processes",
        "ownership_plans",
        "pending_repairs",
        "configuration_backups",
        "configuration_revisions",
        "configuration_plans",
        "operation_jobs",
    ):
        op.drop_table(table)

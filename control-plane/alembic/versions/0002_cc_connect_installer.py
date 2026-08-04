from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_cc_connect_installer"
down_revision = "0001_control_plane_baseline"
branch_labels = None
depends_on = None


def _index(table: str, column: str) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("artifact_id", sa.String(128), primary_key=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("source_ref", sa.String(128), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    _index("artifacts", "component_id")
    op.create_table(
        "install_plans",
        sa.Column("plan_id", sa.String(128), primary_key=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("artifact_id", sa.String(128), nullable=False),
        sa.Column("plan_digest", sa.String(71), nullable=False, unique=True),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("source_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
    )
    for column in ("component_id", "artifact_id", "status"):
        _index("install_plans", column)
    op.create_table(
        "install_snapshots",
        sa.Column("snapshot_id", sa.String(128), primary_key=True),
        sa.Column("operation_id", sa.String(128), nullable=False, unique=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    _index("install_snapshots", "operation_id")
    _index("install_snapshots", "component_id")
    op.create_table(
        "install_records",
        sa.Column("install_record_id", sa.String(128), primary_key=True),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("artifact_id", sa.String(128), nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("relative_path", sa.String(512), nullable=False),
        sa.Column("artifact_sha256", sa.String(64), nullable=False),
        sa.Column("management_owner", sa.String(32), nullable=False),
        sa.Column("installed_at", sa.DateTime(), nullable=False),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
    )
    for column in ("operation_id", "component_id", "artifact_id", "status"):
        _index("install_records", column)
    op.create_table(
        "component_versions",
        sa.Column("artifact_id", sa.String(128), primary_key=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("relative_path", sa.String(512), nullable=False),
        sa.Column("artifact_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("installed_at", sa.DateTime(), nullable=False),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
    )
    for column in ("component_id", "status"):
        _index("component_versions", column)
    op.create_table(
        "pending_cleanup",
        sa.Column("cleanup_id", sa.String(128), primary_key=True),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("relative_path", sa.String(512), nullable=False),
        sa.Column("reason_code", sa.String(128), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    _index("pending_cleanup", "operation_id")
    _index("pending_cleanup", "component_id")
    op.create_table(
        "installation_leases",
        sa.Column("component_id", sa.String(128), primary_key=True),
        sa.Column("operation_id", sa.String(128), nullable=False, unique=True),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "operation_events",
        sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("phase", sa.String(128), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    _index("operation_events", "operation_id")


def downgrade() -> None:
    for table in (
        "operation_events",
        "installation_leases",
        "pending_cleanup",
        "component_versions",
        "install_records",
        "install_snapshots",
        "install_plans",
        "artifacts",
    ):
        op.drop_table(table)

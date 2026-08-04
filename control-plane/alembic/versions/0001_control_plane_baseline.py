from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001_control_plane_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operations",
        sa.Column("operation_id", sa.String(128), primary_key=True),
        sa.Column("kind", sa.String(128), nullable=False),
        sa.Column("target_kind", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("progress_phase", sa.String(128), nullable=False),
        sa.Column("progress_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("completed_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_units", sa.Integer(), nullable=True),
        sa.Column("point_of_no_return", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_json", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_operations_idempotency_key", "operations", ["idempotency_key"])
    op.create_table(
        "idempotency",
        sa.Column("idempotency_key", sa.String(256), primary_key=True),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("resource", sa.String(256), nullable=False),
        sa.Column("body_digest", sa.String(128), nullable=False),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_idempotency_operation_id", "idempotency", ["operation_id"])
    op.create_table(
        "diagnostics",
        sa.Column("diagnostic_id", sa.String(128), primary_key=True),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("suggested_actions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("technical_details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("redaction_applied", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("operation_id", sa.String(128), nullable=True),
        sa.Column("target_kind", sa.String(64), nullable=True),
        sa.Column("target_id", sa.String(128), nullable=True),
    )
    op.create_index("ix_diagnostics_correlation_id", "diagnostics", ["correlation_id"])
    op.create_table(
        "event_cursors",
        sa.Column("epoch", sa.String(128), primary_key=True),
        sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "component_state",
        sa.Column("component_id", sa.String(128), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("version", sa.String(128), nullable=True),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("revision", sa.String(128), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("component_state")
    op.drop_table("event_cursors")
    op.drop_index("ix_diagnostics_correlation_id", table_name="diagnostics")
    op.drop_table("diagnostics")
    op.drop_index("ix_idempotency_operation_id", table_name="idempotency")
    op.drop_table("idempotency")
    op.drop_index("ix_operations_idempotency_key", table_name="operations")
    op.drop_table("operations")

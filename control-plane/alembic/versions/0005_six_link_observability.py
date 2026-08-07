from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_six_link_observability"
down_revision = "0004_telegram_native_config"
branch_labels = None
depends_on = None


def _index(table: str, column: str) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "link_status_records",
        sa.Column("link_id", sa.String(32), primary_key=True),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("evidence_level", sa.String(32), nullable=False),
        sa.Column("last_probe_at", sa.DateTime(), nullable=True),
        sa.Column("last_live_verified_at", sa.DateTime(), nullable=True),
    )
    _index("link_status_records", "status")
    _index("link_status_records", "evidence_level")

    op.create_table(
        "live_e2e_test_plans",
        sa.Column("plan_id", sa.String(128), primary_key=True),
        sa.Column("plan_digest", sa.String(71), nullable=False, unique=True),
        sa.Column("link_id", sa.String(32), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("link_id", "status", "expires_at"):
        _index("live_e2e_test_plans", column)

    op.create_table(
        "live_e2e_test_runs",
        sa.Column("run_id", sa.String(128), primary_key=True),
        sa.Column("plan_id", sa.String(128), nullable=False),
        sa.Column("link_id", sa.String(32), nullable=False),
        sa.Column("lifecycle", sa.String(32), nullable=False),
        sa.Column("evidence_level", sa.String(32), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False, unique=True),
        sa.Column("request_message_id", sa.Integer(), nullable=True),
        sa.Column("response_message_id", sa.Integer(), nullable=True),
        sa.Column("reply_to_message_id", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("diagnostic_code", sa.String(128), nullable=True),
        sa.Column("recovery_actions_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    for column in (
        "plan_id",
        "link_id",
        "lifecycle",
        "evidence_level",
        "correlation_id",
        "idempotency_key",
    ):
        _index("live_e2e_test_runs", column)
    op.create_index(
        "uq_live_e2e_test_runs_plan_id",
        "live_e2e_test_runs",
        ["plan_id"],
        unique=True,
    )

    op.create_table(
        "message_correlation_records",
        sa.Column("correlation_id", sa.String(128), primary_key=True),
        sa.Column("link_id", sa.String(32), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("chat_identity_hash", sa.String(64), nullable=False),
        sa.Column("request_message_id", sa.Integer(), nullable=False),
        sa.Column("response_message_id", sa.Integer(), nullable=True),
        sa.Column("reply_to_message_id", sa.Integer(), nullable=True),
        sa.Column("send_status", sa.String(32), nullable=False),
        sa.Column("response_status", sa.String(32), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("diagnostic_code", sa.String(128), nullable=True),
        sa.Column("consumed", sa.Integer(), nullable=False, server_default="0"),
    )
    for column in (
        "link_id",
        "bot_id",
        "chat_identity_hash",
        "request_message_id",
        "response_status",
    ):
        _index("message_correlation_records", column)

    op.create_table(
        "session_isolation_results",
        sa.Column("probe_id", sa.String(128), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("evidence_level", sa.String(32), nullable=False),
        sa.Column("checks_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    _index("session_isolation_results", "status")
    _index("session_isolation_results", "evidence_level")

    op.create_table(
        "user_validation_sessions",
        sa.Column("session_id", sa.String(128), primary_key=True),
        sa.Column("candidate_version", sa.String(64), nullable=False),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    _index("user_validation_sessions", "candidate_version")
    _index("user_validation_sessions", "state")

    op.create_table(
        "user_validation_steps",
        sa.Column("session_id", sa.String(128), primary_key=True),
        sa.Column("step_id", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    _index("user_validation_steps", "status")

    op.create_table(
        "packaged_candidate_records",
        sa.Column("candidate_id", sa.String(128), primary_key=True),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("architecture", sa.String(32), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("package_sha256", sa.String(64), nullable=False),
        sa.Column("relative_path", sa.String(512), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    _index("packaged_candidate_records", "version")
    _index("packaged_candidate_records", "status")


def downgrade() -> None:
    for table in (
        "packaged_candidate_records",
        "user_validation_steps",
        "user_validation_sessions",
        "session_isolation_results",
        "message_correlation_records",
        "live_e2e_test_runs",
        "live_e2e_test_plans",
        "link_status_records",
    ):
        op.drop_table(table)

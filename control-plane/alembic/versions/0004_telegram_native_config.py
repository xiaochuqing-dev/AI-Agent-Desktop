from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_telegram_native_config"
down_revision = "0003_cc_connect_managed_runtime"
branch_labels = None
depends_on = None


def _index(table: str, column: str) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "credential_references",
        sa.Column("reference_id", sa.String(128), primary_key=True),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("backend", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in ("purpose", "backend", "status"):
        _index("credential_references", column)

    op.create_table(
        "credential_revisions",
        sa.Column("reference_id", sa.String(128), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("operation_id", "status"):
        _index("credential_revisions", column)

    op.create_table(
        "telegram_bot_identities",
        sa.Column("slot", sa.String(32), primary_key=True),
        sa.Column("bot_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("first_name", sa.String(256), nullable=False),
        sa.Column("can_join_groups", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("can_read_all_group_messages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credential_reference_id", sa.String(128), nullable=False),
        sa.Column("credential_revision", sa.Integer(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=False),
        sa.Column("verification_status", sa.String(32), nullable=False),
    )
    for column in ("bot_id", "credential_reference_id", "verification_status"):
        _index("telegram_bot_identities", column)

    op.create_table(
        "telegram_update_leases",
        sa.Column("bot_slot", sa.String(32), primary_key=True),
        sa.Column("owner", sa.String(64), nullable=False),
        sa.Column("operation_id", sa.String(128), nullable=True),
        sa.Column("credential_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("acquired_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("release_reason", sa.String(128), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    for column in ("owner", "operation_id"):
        _index("telegram_update_leases", column)

    op.create_table(
        "telegram_binding_sessions",
        sa.Column("session_id", sa.String(128), primary_key=True),
        sa.Column("code_digest", sa.String(128), nullable=False),
        sa.Column("state", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("operator_user_id", sa.Integer(), nullable=True),
        sa.Column("group_chat_id", sa.Integer(), nullable=True),
        sa.Column("group_title", sa.String(512), nullable=True),
        sa.Column("group_type", sa.String(32), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("canceled_at", sa.DateTime(), nullable=True),
        sa.Column("failure_code", sa.String(128), nullable=True),
    )
    for column in ("state", "expires_at"):
        _index("telegram_binding_sessions", column)

    op.create_table(
        "telegram_binding_slots",
        sa.Column("session_id", sa.String(128), primary_key=True),
        sa.Column("slot", sa.String(32), primary_key=True),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("credential_revision", sa.Integer(), nullable=False),
        sa.Column("private_status", sa.String(32), nullable=False),
        sa.Column("group_status", sa.String(32), nullable=False),
        sa.Column("private_user_id", sa.Integer(), nullable=True),
        sa.Column("group_chat_id", sa.Integer(), nullable=True),
        sa.Column("group_title", sa.String(512), nullable=True),
        sa.Column("group_type", sa.String(32), nullable=True),
        sa.Column("private_update_id", sa.Integer(), nullable=True),
        sa.Column("group_update_id", sa.Integer(), nullable=True),
        sa.Column("last_update_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in ("bot_id", "private_status", "group_status"):
        _index("telegram_binding_slots", column)

    op.create_table(
        "telegram_group_bindings",
        sa.Column("session_id", sa.String(128), primary_key=True),
        sa.Column("slot", sa.String(32), primary_key=True),
        sa.Column("operator_user_id", sa.Integer(), nullable=False),
        sa.Column("group_chat_id", sa.Integer(), nullable=False),
        sa.Column("group_title", sa.String(512), nullable=True),
        sa.Column("group_type", sa.String(32), nullable=False),
        sa.Column("binding_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("operator_user_id", "group_chat_id"):
        _index("telegram_group_bindings", column)

    op.create_table(
        "telegram_binding_audits",
        sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("slot", sa.String(32), nullable=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("session_id", "event_type"):
        _index("telegram_binding_audits", column)

    op.create_table(
        "native_configuration_plans",
        sa.Column("plan_id", sa.String(128), primary_key=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("artifact_id", sa.String(128), nullable=False),
        sa.Column("plan_digest", sa.String(71), nullable=False, unique=True),
        sa.Column("context_digest", sa.String(71), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("runtime_payload_json", sa.Text(), nullable=False),
        sa.Column("managed_payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
    )
    for column in ("component_id", "artifact_id", "status"):
        _index("native_configuration_plans", column)

    op.create_table(
        "native_configuration_revisions",
        sa.Column("component_id", sa.String(128), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("artifact_id", sa.String(128), nullable=False),
        sa.Column("plan_id", sa.String(128), nullable=False),
        sa.Column("runtime_payload_json", sa.Text(), nullable=False),
        sa.Column("managed_payload_json", sa.Text(), nullable=False),
        sa.Column("runtime_config_digest", sa.String(71), nullable=False),
        sa.Column("managed_state_digest", sa.String(71), nullable=False),
        sa.Column("runtime_config_relative_path", sa.String(512), nullable=False),
        sa.Column("managed_state_relative_path", sa.String(512), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("artifact_id", "plan_id", "status"):
        _index("native_configuration_revisions", column)

    op.create_table(
        "native_configuration_backups",
        sa.Column("backup_id", sa.String(128), primary_key=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("runtime_relative_path", sa.String(512), nullable=True),
        sa.Column("managed_relative_path", sa.String(512), nullable=True),
        sa.Column("runtime_digest", sa.String(71), nullable=True),
        sa.Column("managed_digest", sa.String(71), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("component_id", "operation_id", "status"):
        _index("native_configuration_backups", column)

    op.create_table(
        "component_config_renderers",
        sa.Column("renderer_id", sa.String(128), primary_key=True),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("renderer_version", sa.String(128), nullable=False),
        sa.Column("source_commit", sa.String(64), nullable=False),
        sa.Column("capability_json", sa.Text(), nullable=False),
        sa.Column("active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in ("component_id", "renderer_version"):
        _index("component_config_renderers", column)

    op.create_table(
        "runtime_secret_injection_audits",
        sa.Column("audit_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("component_id", sa.String(128), nullable=False),
        sa.Column("environment_variables_json", sa.Text(), nullable=False),
        sa.Column("credential_references_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("operation_id", "component_id", "status"):
        _index("runtime_secret_injection_audits", column)

    op.create_table(
        "hermes_configuration_plans",
        sa.Column("plan_id", sa.String(128), primary_key=True),
        sa.Column("binding_session_id", sa.String(128), nullable=False),
        sa.Column("plan_digest", sa.String(71), nullable=False, unique=True),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("binding_session_id", "status"):
        _index("hermes_configuration_plans", column)


def downgrade() -> None:
    for table in (
        "hermes_configuration_plans",
        "runtime_secret_injection_audits",
        "component_config_renderers",
        "native_configuration_backups",
        "native_configuration_revisions",
        "native_configuration_plans",
        "telegram_binding_audits",
        "telegram_group_bindings",
        "telegram_binding_slots",
        "telegram_binding_sessions",
        "telegram_update_leases",
        "telegram_bot_identities",
        "credential_revisions",
        "credential_references",
    ):
        op.drop_table(table)

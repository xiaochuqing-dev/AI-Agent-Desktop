from __future__ import annotations

from sqlalchemy import inspect, text

from alembic import command
from control_plane.infrastructure.config import Settings
from control_plane.persistence.migration import _config
from control_plane.persistence.models import (
    Base,
    ComponentStateRecord,
    DiagnosticRecord,
    EventCursorRecord,
    IdempotencyRecord,
    OperationRecord,
)
from control_plane.persistence.session import Database, make_engine

INSTALLER_TABLES = {
    "artifacts",
    "install_plans",
    "install_snapshots",
    "install_records",
    "component_versions",
    "pending_cleanup",
    "installation_leases",
    "operation_events",
}

RUNTIME_TABLES = {
    "operation_jobs",
    "configuration_plans",
    "configuration_revisions",
    "configuration_backups",
    "pending_repairs",
    "ownership_plans",
    "managed_processes",
    "process_identity_records",
    "port_ownership_records",
    "lifecycle_leases",
    "lifecycle_events",
    "external_tool_capabilities",
    "update_assessments",
    "credential_references",
    "credential_revisions",
    "telegram_bot_identities",
    "telegram_update_leases",
    "telegram_binding_sessions",
    "telegram_binding_slots",
    "telegram_group_bindings",
    "telegram_binding_audits",
    "native_configuration_plans",
    "native_configuration_revisions",
    "native_configuration_backups",
    "component_config_renderers",
    "runtime_secret_injection_audits",
    "hermes_configuration_plans",
}


def test_empty_database_migrates_to_head(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    tables = set(inspect(database.engine).get_table_names())
    assert INSTALLER_TABLES.issubset(tables)
    assert RUNTIME_TABLES.issubset(tables)
    with database.engine.connect() as connection:
        assert connection.scalar(text("select version_num from alembic_version")) == (
            "0004_telegram_native_config"
        )


def test_legacy_create_all_schema_is_stamped_and_upgraded(tmp_path):
    engine = make_engine(str(tmp_path / "legacy.db"))
    Base.metadata.create_all(
        engine,
        tables=[
            OperationRecord.__table__,
            IdempotencyRecord.__table__,
            DiagnosticRecord.__table__,
            EventCursorRecord.__table__,
            ComponentStateRecord.__table__,
        ],
    )
    database = Database(Settings(data_dir=str(tmp_path), db_filename="legacy.db"))
    assert INSTALLER_TABLES.issubset(set(inspect(database.engine).get_table_names()))
    assert RUNTIME_TABLES.issubset(set(inspect(database.engine).get_table_names()))


def test_repeated_migration_is_idempotent(tmp_path):
    settings = Settings(data_dir=str(tmp_path))
    first = Database(settings)
    first.engine.dispose()
    second = Database(settings)
    with second.engine.connect() as connection:
        rows = connection.execute(text("select version_num from alembic_version")).all()
    assert rows == [("0004_telegram_native_config",)]


def test_current_0002_database_upgrades_without_losing_installer_tables(tmp_path):
    engine = make_engine(str(tmp_path / "upgrade.db"))
    with engine.begin() as connection:
        command.upgrade(_config(connection), "0002_cc_connect_installer")
    assert not RUNTIME_TABLES.intersection(inspect(engine).get_table_names())
    engine.dispose()

    database = Database(Settings(data_dir=str(tmp_path), db_filename="upgrade.db"))
    tables = set(inspect(database.engine).get_table_names())
    assert INSTALLER_TABLES.issubset(tables)
    assert RUNTIME_TABLES.issubset(tables)


def test_runtime_migration_has_reversible_schema_strategy(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    with database.engine.begin() as connection:
        command.downgrade(_config(connection), "0002_cc_connect_installer")
    tables = set(inspect(database.engine).get_table_names())
    assert INSTALLER_TABLES.issubset(tables)
    assert not RUNTIME_TABLES.intersection(tables)
    with database.engine.begin() as connection:
        command.upgrade(_config(connection), "head")
    assert RUNTIME_TABLES.issubset(set(inspect(database.engine).get_table_names()))

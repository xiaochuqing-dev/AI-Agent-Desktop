from __future__ import annotations

from sqlalchemy import inspect, text

from control_plane.infrastructure.config import Settings
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


def test_empty_database_migrates_to_head(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    tables = set(inspect(database.engine).get_table_names())
    assert INSTALLER_TABLES.issubset(tables)
    with database.engine.connect() as connection:
        assert connection.scalar(text("select version_num from alembic_version")) == (
            "0002_cc_connect_installer"
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


def test_repeated_migration_is_idempotent(tmp_path):
    settings = Settings(data_dir=str(tmp_path))
    first = Database(settings)
    first.engine.dispose()
    second = Database(settings)
    with second.engine.connect() as connection:
        rows = connection.execute(text("select version_num from alembic_version")).all()
    assert rows == [("0002_cc_connect_installer",)]

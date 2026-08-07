from __future__ import annotations

import sys
from pathlib import Path

from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from alembic import command

BASELINE_REVISION = "0001_control_plane_baseline"
LEGACY_TABLES = {
    "operations",
    "idempotency",
    "diagnostics",
    "event_cursors",
    "component_state",
}


def _control_plane_root() -> Path:
    """Return the root containing Alembic resources in source and frozen runs."""

    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(str(bundled_root)).resolve()
    return Path(__file__).resolve().parents[2]


def _config(connection) -> Config:
    control_plane_root = _control_plane_root()
    alembic_ini = control_plane_root / "alembic.ini"
    script_location = control_plane_root / "alembic"
    if not alembic_ini.is_file() or not script_location.is_dir():
        raise RuntimeError(
            f"Alembic migration resources are missing from the candidate package: {script_location}"
        )
    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(script_location))
    config.attributes["connection"] = connection
    return config


def run_migrations(engine: Engine) -> None:
    """Upgrade an empty or legacy create_all database to the current schema."""
    with engine.begin() as connection:
        tables = set(inspect(connection).get_table_names())
        config = _config(connection)
        if tables and "alembic_version" not in tables:
            if not LEGACY_TABLES.issubset(tables):
                raise RuntimeError("database schema is not a recognized Control Plane baseline")
            command.stamp(config, BASELINE_REVISION)
        command.upgrade(config, "head")

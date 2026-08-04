from __future__ import annotations

from typing import Protocol

from .models import ManagedConfiguration


class ConfigurationMigration(Protocol):
    from_schema_version: str
    to_schema_version: str

    def migrate(self, configuration: dict) -> ManagedConfiguration: ...


class ConfigurationMigrationRegistry:
    """Explicit future migration entrypoint; this slice has only schema 1.0."""

    def __init__(self) -> None:
        self._migrations: dict[tuple[str, str], ConfigurationMigration] = {}

    def register(self, migration: ConfigurationMigration) -> None:
        key = (migration.from_schema_version, migration.to_schema_version)
        if key in self._migrations:
            raise ValueError(f"configuration migration already registered: {key}")
        self._migrations[key] = migration

    def assess(self, from_version: str, to_version: str) -> str:
        if from_version == to_version:
            return "not_required"
        return "planned" if (from_version, to_version) in self._migrations else "unsupported"

    def migrate(
        self, configuration: dict, *, from_version: str, to_version: str
    ) -> ManagedConfiguration:
        if from_version == to_version:
            return ManagedConfiguration.model_validate(configuration)
        migration = self._migrations.get((from_version, to_version))
        if migration is None:
            raise ValueError(f"unsupported configuration migration: {from_version} -> {to_version}")
        return migration.migrate(configuration)

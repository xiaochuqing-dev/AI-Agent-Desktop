from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from typing import Literal

import httpx

from ..credentials.service import CredentialService
from ..credentials.windows_backend import CredentialBackendError
from ..persistence.models import RuntimeSecretInjectionAuditRecord
from ..persistence.session import Database
from .native_config_models import NativeRuntimeConfig


def utcnow() -> datetime:
    return datetime.now(UTC)


class RuntimeSecretInjector:
    def __init__(self, database: Database, credentials: CredentialService) -> None:
        self.db = database
        self.credentials = credentials

    @contextmanager
    def environment(
        self,
        config: NativeRuntimeConfig,
        *,
        operation_id: str,
        product_instance_id: str,
    ) -> Iterator[dict[str, str]]:
        allowed = {
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATH",
            "PATHEXT",
            "TEMP",
            "TMP",
            "LOCALAPPDATA",
            "APPDATA",
            "USERPROFILE",
            "HOMEDRIVE",
            "HOMEPATH",
            "LANG",
        }
        environment = {name: value for name in allowed if (value := os.environ.get(name))}
        references = {
            config.management_environment_variable: config.management_credential_reference_id,
            **{
                project.telegram.environment_variable: project.telegram.credential_reference_id
                for project in config.projects
            },
        }
        with ExitStack() as stack:
            for variable_name, reference_id in references.items():
                value = stack.enter_context(self.credentials.resolve_for_operation(reference_id))
                environment[variable_name] = value
            environment.update(
                {
                    "CC_CONNECT_MANAGED_INSTANCE": product_instance_id,
                    "CC_CONNECT_MANAGED_LISTEN_HOST": "127.0.0.1",
                    "CC_CONNECT_MANAGED_LISTEN_PORT": str(config.management_port),
                }
            )
            self._audit(operation_id, references, "injected")
            try:
                yield environment
            finally:
                for variable_name in references:
                    environment[variable_name] = ""
                environment.clear()
                self._audit(operation_id, references, "released")

    def probe_management_status(
        self, config: NativeRuntimeConfig
    ) -> Literal["verified", "auth_failed", "unreachable"]:
        try:
            with self.credentials.resolve_for_operation(
                config.management_credential_reference_id
            ) as token:
                response = httpx.get(
                    f"http://127.0.0.1:{config.management_port}/api/v1/status",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=3.0,
                    trust_env=False,
                )
                if response.status_code == 200:
                    return "verified"
                if response.status_code in {401, 403}:
                    return "auth_failed"
                return "unreachable"
        except (httpx.HTTPError, CredentialBackendError):
            return "unreachable"

    def probe_management(self, config: NativeRuntimeConfig) -> bool:
        return self.probe_management_status(config) == "verified"

    def _audit(self, operation_id: str, references: dict[str, str], status: str) -> None:
        with self.db.session() as session:
            session.add(
                RuntimeSecretInjectionAuditRecord(
                    operation_id=operation_id,
                    component_id="cc-connect",
                    environment_variables_json=__import__("json").dumps(sorted(references)),
                    credential_references_json=__import__("json").dumps(
                        sorted(references.values())
                    ),
                    status=status,
                    created_at=utcnow(),
                )
            )

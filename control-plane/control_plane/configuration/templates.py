from __future__ import annotations

import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .models import (
    HealthProbeConfiguration,
    LifecycleOwner,
    ManagedConfiguration,
    ManagementOwner,
    SecretReference,
    TelegramConfiguration,
)


def build_minimal_configuration(
    *,
    artifact_id: str,
    product_instance_id: str,
    listen_port: int,
    component_root: Path,
    revision: int,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    secret_backend: Literal["windows_credential_manager", "memory"] = "windows_credential_manager",
) -> ManagedConfiguration:
    now = datetime.now(UTC)
    return ManagedConfiguration(
        artifact_id=artifact_id,
        product_instance_id=product_instance_id,
        listen_port=listen_port,
        data_dir=str((component_root / "state" / "runtime-data").resolve(strict=False)),
        log_dir=str((component_root / "state" / "logs").resolve(strict=False)),
        project_root=str((component_root / "state" / "project-placeholder").resolve(strict=False)),
        lifecycle_owner=LifecycleOwner.PRODUCT,
        management_owner=ManagementOwner.PRODUCT,
        configuration_revision=revision,
        created_at=created_at or now,
        updated_at=updated_at or now,
        secret_refs=[
            SecretReference(
                reference_id="telegram-bot-token",
                backend=secret_backend,
                purpose="telegram_bot_token",
                required=False,
            )
        ],
        telegram=TelegramConfiguration(),
        health_probe=HealthProbeConfiguration(),
    )


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_managed_toml(configuration: ManagedConfiguration) -> bytes:
    value = configuration
    lines = [
        f"schema_version = {_quote(value.schema_version)}",
        f"component_id = {_quote(value.component_id)}",
        f"artifact_id = {_quote(value.artifact_id)}",
        f"product_instance_id = {_quote(value.product_instance_id)}",
        f"listen_host = {_quote(value.listen_host)}",
        f"listen_port = {value.listen_port}",
        f"data_dir = {_quote(value.data_dir)}",
        f"log_dir = {_quote(value.log_dir)}",
        f"project_root = {_quote(value.project_root)}",
        f"lifecycle_owner = {_quote(value.lifecycle_owner.value)}",
        f"management_owner = {_quote(value.management_owner.value)}",
        f"configuration_revision = {value.configuration_revision}",
        f"created_at = {_quote(value.created_at.isoformat())}",
        f"updated_at = {_quote(value.updated_at.isoformat())}",
        f"network_mode = {_quote(value.network_mode)}",
        "",
        "[telegram]",
        "enabled = false",
        f"mode = {_quote(value.telegram.mode)}",
        "",
        "[health_probe]",
        f"startup_timeout_seconds = {value.health_probe.startup_timeout_seconds}",
        f"stable_window_seconds = {value.health_probe.stable_window_seconds}",
        "local_endpoint_supported = false",
        f"deep_health = {_quote(value.health_probe.deep_health)}",
    ]
    for reference in value.secret_refs:
        lines.extend(
            [
                "",
                "[[secret_refs]]",
                f"reference_id = {_quote(reference.reference_id)}",
                f"backend = {_quote(reference.backend)}",
                f"purpose = {_quote(reference.purpose)}",
                f"required = {'true' if reference.required else 'false'}",
            ]
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def parse_managed_toml(data: bytes) -> ManagedConfiguration:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    decoded = data.decode("utf-8", errors="strict")
    return ManagedConfiguration.model_validate(tomllib.loads(decoded))

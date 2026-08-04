from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Literal

from ..credentials.models import INTERNAL_CC_CONNECT_MANAGEMENT_REFERENCE
from .native_config_models import NativeRendererCapability, NativeRuntimeConfig


class NativeConfigRenderError(ValueError):
    pass


class CcConnectNativeConfigRenderer:
    renderer_version: Literal["cc-connect-fc315d2-native-v1"] = "cc-connect-fc315d2-native-v1"
    source_commit: Literal["fc315d213b49d62e9d90ea4a510189d4115e636f"] = (
        "fc315d213b49d62e9d90ea4a510189d4115e636f"
    )

    def capability(self) -> NativeRendererCapability:
        return NativeRendererCapability(
            renderer_version=self.renderer_version,
            source_commit=self.source_commit,
            project_types=["claudecode", "codex"],
        )

    def render(self, config: NativeRuntimeConfig) -> bytes:
        self.validate(config)
        lines = [
            f"data_dir = {self._quote(config.data_dir)}",
            'language = "zh"',
            "",
            "[log]",
            'level = "info"',
            "",
            "[management]",
            "enabled = true",
            f"port = {config.management_port}",
            f'token = "${{{config.management_environment_variable}}}"',
        ]
        for project in config.projects:
            lines.extend(
                [
                    "",
                    "[[projects]]",
                    f"name = {self._quote(project.project_id)}",
                    f"admin_from = {self._quote(project.admin_from)}",
                    "inject_sender = true",
                    'disabled_commands = ["upgrade"]',
                    "",
                    "[projects.agent]",
                    f"type = {self._quote(project.agent_type)}",
                    "",
                    "[projects.agent.options]",
                    f"work_dir = {self._quote(project.workspace_root)}",
                    "",
                    "[[projects.platforms]]",
                    'type = "telegram"',
                    "",
                    "[projects.platforms.options]",
                    f'token = "${{{project.telegram.environment_variable}}}"',
                    f"allow_from = {self._quote(project.telegram.allow_from)}",
                    "group_reply_all = false",
                    "share_session_in_channel = false",
                    'progress_style = "compact"',
                ]
            )
        data = ("\n".join(lines) + "\n").encode("utf-8")
        self.validate_rendered(data, config)
        return data

    def validate(self, config: NativeRuntimeConfig) -> None:
        if config.management_credential_reference_id != INTERNAL_CC_CONNECT_MANAGEMENT_REFERENCE:
            raise NativeConfigRenderError("unexpected management credential reference")
        for value in (
            config.data_dir,
            config.log_dir,
            *(p.workspace_root for p in config.projects),
        ):
            path = Path(value)
            if not path.is_absolute():
                raise NativeConfigRenderError("cc-connect native paths must be absolute")
        for project in config.projects:
            expected_env = (
                "AIAD_TELEGRAM_CLAUDE_BOT_TOKEN"
                if project.slot == "claude"
                else "AIAD_TELEGRAM_CODEX_BOT_TOKEN"
            )
            if project.telegram.environment_variable != expected_env:
                raise NativeConfigRenderError("unexpected locked bot environment variable")
            if project.telegram.allow_from != str(project.operator_user_id):
                raise NativeConfigRenderError("allow_from must be the bound operator user id")
            if project.admin_from != str(project.operator_user_id):
                raise NativeConfigRenderError("admin_from must be the bound operator user id")

    def validate_rendered(self, data: bytes, config: NativeRuntimeConfig) -> None:
        if data.startswith(b"\xef\xbb\xbf"):
            raise NativeConfigRenderError("native config must be UTF-8 without BOM")
        decoded = data.decode("utf-8", errors="strict")
        parsed = tomllib.loads(decoded)
        if set(parsed) - {"data_dir", "language", "log", "management", "projects"}:
            raise NativeConfigRenderError("renderer emitted unsupported top-level fields")
        projects = parsed.get("projects")
        if not isinstance(projects, list) or len(projects) != len(config.projects):
            raise NativeConfigRenderError("renderer did not emit the expected projects")
        if parsed.get("management", {}).get("token") != "${AIAD_CC_CONNECT_MANAGEMENT_TOKEN}":
            raise NativeConfigRenderError("management secret placeholder was not preserved")
        for rendered, expected in zip(projects, config.projects, strict=True):
            if rendered.get("name") != expected.project_id:
                raise NativeConfigRenderError("project name changed during rendering")
            platforms = rendered.get("platforms")
            if not isinstance(platforms, list) or len(platforms) != 1:
                raise NativeConfigRenderError("project must contain one Telegram platform")
            token = platforms[0].get("options", {}).get("token")
            if token != f"${{{expected.telegram.environment_variable}}}":
                raise NativeConfigRenderError("Telegram secret placeholder was not preserved")
        forbidden = (
            "product_instance_id",
            "management_owner",
            "lifecycle_owner",
            "configuration_revision",
            "credential_reference_id",
            "group_chat_id",
        )
        if any(item in decoded for item in forbidden):
            raise NativeConfigRenderError("product management metadata leaked into native TOML")

    @staticmethod
    def _quote(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

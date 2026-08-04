# 配置:所有路径经 platformdirs 或环境变量解析,禁止写死用户名与绝对路径。
# 本地服务默认只绑 loopback。端口默认 58080(与 OpenAPI 示例一致),属开放实现参数。
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_data_dir


def default_data_dir() -> str:
    # 平台用户数据目录,Windows 下为 %LOCALAPPDATA%/<app>/control-plane
    return user_data_dir("AI-Agent-Desktop", appauthor=False)


@dataclass
class Settings:
    # 服务运行配置。所有数值带注释说明含义与单位。
    bind_host: str = "127.0.0.1"  # 仅 loopback,禁止绑定非本地地址
    bind_port: int = 58080  # 默认端口,开放实现参数,可在环境变量覆盖
    data_dir: str = field(default_factory=default_data_dir)
    db_filename: str = "control_plane.db"
    # Operation 与幂等记录保留窗口,默认 7 天(单位:天)
    operation_retention_days: int = 7
    # HTTP 短同步预算,超出改为 202 Operation(单位:秒)
    short_request_budget_seconds: int = 5
    # 本地 API Bearer token 来源:环境变量名
    bearer_token_env: str = "CONTROL_PLANE_API_TOKEN"
    contract_version: str = "1.0.0"
    service_version: str = "0.1.0"
    trusted_artifact_dir: str | None = None
    artifact_max_bytes: int = 128 * 1024 * 1024
    download_timeout_seconds: int = 30
    download_retries: int = 3
    allowed_download_hosts: tuple[str, ...] = (
        "github.com",
        "api.github.com",
        "objects.githubusercontent.com",
        "raw.githubusercontent.com",
    )

    @property
    def db_path(self) -> str:
        return str(Path(self.data_dir) / self.db_filename)

    @property
    def components_dir(self) -> str:
        return str(Path(self.data_dir) / "components")

    def ensure_data_dir(self) -> None:
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)

    def bearer_token(self) -> str:
        # 启动时从环境读取;不存在则生成一次随机 token 并提示(开发态)。
        # 真实 token 永不入日志、不入 URL query、不持久化明文到普通配置。
        token = os.environ.get(self.bearer_token_env)
        if not token:
            token = secrets.token_urlsafe(32)  # 256 bit 高熵
            os.environ[self.bearer_token_env] = token
        return token

    @classmethod
    def from_env(cls) -> Settings:
        port = os.environ.get("CONTROL_PLANE_PORT")
        bind_port = int(port) if port else cls.bind_port
        data_dir = os.environ.get("CONTROL_PLANE_DATA_DIR") or default_data_dir()
        trusted_artifact_dir = os.environ.get("CONTROL_PLANE_CC_CONNECT_ARTIFACT_DIR")
        return cls(
            bind_port=bind_port,
            data_dir=data_dir,
            trusted_artifact_dir=trusted_artifact_dir,
        )

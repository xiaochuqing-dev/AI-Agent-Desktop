# 入口:uvicorn 启动 Control Plane,绑定 loopback。
# 用法:python -m control_plane.main  或  control-plane-serve
from __future__ import annotations

import uvicorn

from .api.app import create_app
from .infrastructure.config import Settings


def main() -> None:
    settings = Settings.from_env()
    app = create_app(settings)
    print(f"Control Plane 启动: http://{settings.bind_host}:{settings.bind_port}/api/v1")
    print(f"数据目录: {settings.data_dir}")
    print("仅绑定 loopback。Bearer token 见环境变量 CONTROL_PLANE_API_TOKEN。")
    uvicorn.run(app, host=settings.bind_host, port=settings.bind_port, log_level="info")


if __name__ == "__main__":
    main()

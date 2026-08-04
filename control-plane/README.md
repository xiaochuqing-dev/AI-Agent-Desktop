Control Plane 本地控制面
=======================

本目录是 AI Agent Desktop 的独立 Local Control Plane。服务仅绑定 loopback，使用 Bearer，并与 src/ Reference Baseline 物理隔离。

当前已实现两类能力。第一类是 Windows System、Hermes、cc-connect、Claude Code、Codex、CC Switch、Telegram Config 的只读发现、Readiness、DryRun、Diagnostic、Operation 和 SSE。第二类仅针对 cc-connect：锁定产物安装计划、计划摘要确认、普通用户隔离安装、SHA256 与 PE 校验、version-only 离线探针、原子激活、自动回滚、卸载、恢复和 pending_cleanup。

其他组件安装、配置与凭据写入、登录、启动停止接管、Telegram 自动绑定、真实消息验证和 GUI 均为 unsupported 或 planned。

一、目录
--------

control_plane/ 为领域、应用、API、安装器、持久化、安全和 Adapter 代码。
alembic/ 为基线与 cc-connect 安装状态迁移。
tests/ 为单元、契约、迁移、集成和失败矩阵测试。
scripts/windows_isolated_acceptance.py 为真实 Windows 临时 LocalAppData 验收。

二、开发命令
------------

从本目录执行：

1. python -m pip install -e ".[dev]"
2. python -m control_plane.main
3. ruff check .
4. ruff format --check .
5. mypy control_plane
6. pytest -q
7. python scripts/validate_contracts.py

默认地址为 http://127.0.0.1:58080/api/v1。CONTROL_PLANE_API_TOKEN 提供 Bearer；CONTROL_PLANE_CC_CONNECT_ARTIFACT_DIR 可指向受信任的本地构建 bundle。

三、安装布局
------------

默认根目录由 platformdirs 解析为当前用户 LocalAppData 下的 AI-Agent-Desktop。cc-connect 使用 components/cc-connect/current.json、versions、staging、backups 和 state。每个版本独立，current.json 原子替换，不覆盖全局 npm 或运行中的外部 cc-connect.exe，不修改 PATH、计划任务或 Watchdog。

四、安全边界
------------

远程产物只允许锁定 HTTPS 主机，TLS 校验不可关闭；本地 bundle 必须位于显式受信任目录。所有下载在 staging 中完成，并在执行前校验 Manifest、大小、SHA256、平台和架构。健康探针不连接 Telegram，不读取真实配置，不显示窗口，并在超时后清理进程树。SQLite 不保存 Secret 明文。

五、契约
--------

机器契约位于 contracts/control-plane-v1。cc-connect 增量包括 install-plan、install、uninstall、restore、managed-versions、持久化 Operation 事件和安装相关模型。客户端必须忽略未知向后兼容字段。

Control Plane 本地控制面
=======================

本目录是 AI Agent Desktop 的独立 Local Control Plane。服务仅绑定 loopback，使用 Bearer，并与 src/ Reference Baseline 物理隔离。

当前已实现五类能力。第一类是 Windows System、Hermes、cc-connect、Claude Code、Codex、CC Switch、Telegram Config 的只读发现、Readiness、DryRun、Diagnostic、Operation 和 SSE。第二类针对产品自有 cc-connect：锁定产物隔离安装、managed/native 配置分离、锁定 Renderer、revision/备份/回滚、所有权交接、Secret 注入、启停重启、进程身份、端口所有权、management API 与重启恢复。第三类针对三个固定 Telegram Bot：Windows Credential Manager、getMe 身份、Webhook、Update Lease、一次性绑定与 User/Group ID 一致性。第四类是六 LinkState、一次性 E2E 计划、消息关联、Session 隔离探针、显式 Telegram 代理策略和自包含 Windows 验收向导。第五类是最小 PySide6 GUI：四步 Onboarding、Dashboard、Diagnostics、QR、Telegram 深链接/fallback，以及 `/onboarding/snapshot`、`/dashboard/snapshot`、`/telegram/client-availability` 的脱敏 GUI 读模型。

Fake Telegram、合成 Token 和合法 Claude/Codex Project 的真实 cc-connect 进程验收已通过。2026-08-07 用户直接在旧入口 Telegram 验证 Hermes、Claude Code、Codex 的私聊与群聊六条链路并明确通过；该路径没有生成向导 getMe、3/3 绑定或 correlation 持久化证据，也不覆盖新 GUI。整体仍为 PARTIAL：新 GUI 私聊/群自动检测为 `PENDING USER LIVE VALIDATION`，Windows 10 为 `PENDING WINDOWS 10 VALIDATION`；锁定上游 Group Chat 过滤和 deep health 为 unsupported，management API 监听所有网卡。MSI/正式安装器/签名为 `DEFERRED`，其他组件安装/生命周期仍为 unsupported 或 planned。

一、目录
--------

control_plane/ 为领域、应用、API、OperationExecutor、安装器、配置、生命周期、更新/外部工具边界、网络代理、六链路可观测性、验证向导、持久化、安全和 Adapter 代码。
alembic/ 为基线、cc-connect 安装/受管运行、Telegram 凭据/绑定、原生配置和六链路观测状态迁移。
tests/ 为单元、契约、迁移、集成和失败矩阵测试。
scripts/windows_isolated_acceptance.py 为真实 Windows 临时 LocalAppData 验收。
scripts/windows_managed_runtime_acceptance.py 为真实锁定产物的配置、所有权、生命周期、冲突与恢复验收。
scripts/windows_credential_manager_acceptance.py 为普通用户 Windows Credential Manager 合成凭据验收。
scripts/windows_native_runtime_acceptance.py 为三 Fake Bot 绑定、原生配置和真实 cc-connect 进程联合验收。
scripts/production_only_acceptance.py 验证只安装正式依赖时可加载正式 Router/Service 并通过健康检查，且不访问真实 Telegram。
scripts/build_windows_candidate.ps1 构建无需外部 Python、Go 或 Node 的 Windows x64 GUI candidate。
scripts/windows10_user_acceptance.ps1 为 Windows 10 用户验收入口，其存在不代表 Windows 10 已验证。
control_plane/gui/ 为 PySide6 GUI；`python -m control_plane.gui.app --demo` 用于离线预览，`--screenshot <path>` 保存截图，`--version` 输出候选版本。默认真实模式使用 Embedded Control Plane；Demo 状态不能当成 Telegram live。
scripts/gui_candidate_entry.py 提供 `--version`、`--headless`、`--demo` 和 `--screenshot` 入口；`0.2.0-gui` candidate 已在 Windows 11 x64 构建并通过本地 validator。

二、开发命令
------------

从本目录执行：

1. python -m pip install --require-hashes -r requirements-build.lock
2. python -m pip install --require-hashes -r requirements-dev.lock
3. python -m pip install --no-deps --no-build-isolation -e .
4. python -m control_plane.main
5. ruff check .
6. ruff format --check .
7. mypy control_plane
8. pytest -q
9. python scripts/validate_contracts.py
10. python -m pytest -q tests/test_gui.py tests/test_onboarding_api.py

默认地址为 http://127.0.0.1:58080/api/v1。CONTROL_PLANE_API_TOKEN 提供 Bearer；CONTROL_PLANE_CC_CONNECT_ARTIFACT_DIR 可指向受信任的本地构建 bundle。

三、安装布局
------------

默认根目录由 platformdirs 解析为当前用户 LocalAppData 下的 AI-Agent-Desktop。cc-connect 使用 components/cc-connect/current.json、versions、staging、backups 和 state；旧兼容配置位于 state/config/cc-connect.managed.toml，产品管理状态位于 state/managed/cc-connect-state.json，锁定上游原生配置位于 state/runtime-config/cc-connect.toml。每个版本独立，current.json 和配置均原子替换，不覆盖全局 npm 或运行中的外部 cc-connect.exe，不修改 PATH、注册表、计划任务或 Watchdog。

四、安全边界
------------

远程产物只允许锁定 HTTPS 主机，TLS 校验不可关闭；本地 bundle 必须位于显式受信任目录。所有下载在 staging 中完成，并在执行前校验 Manifest、大小、SHA256、平台和架构。默认健康探针、CI 和 headless 检查不连接 Telegram、不发送消息。真实 E2E 需要逐链路不可变计划、显式确认和 Idempotency-Key，每次最多一条且不自动重试。Bot Token 只在 Windows Credential Manager，原生 TOML 只含环境变量占位符，SQLite 不保存 Secret、绑定码明文或消息正文。

五、契约
--------

机器契约位于 contracts/control-plane-v1。增量除 install/configuration/ownership/lifecycle/update 外，还包括 Credential capability/put/replace/status/delete、Telegram Bot identity/webhook/update lease/binding、Native Renderer/plan/apply/state、external cc-connect、Hermes Telegram plan/state 和 onboarding/dashboard snapshot。`onboarding.schema.json` 保存 GUI 读模型，客户端必须忽略未知向后兼容字段；Secret、bind code、消息正文和登录状态不属于 GUI 快照。

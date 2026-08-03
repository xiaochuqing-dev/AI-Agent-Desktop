Control Plane(本地控制面)
=============================

本目录是 AI Agent Desktop 的 Local Control Plane 实现代码区,与 src/ 参考基线物理隔离。

当前阶段交付:一个独立运行、绑定 loopback 的本地服务,对一台 Windows 电脑执行无副作用的"就绪扫描",输出可机器读取、也可被用户理解的就绪报告、结构化 Diagnostic 与 dry-run 安装/修复计划。

内置 7 个只读发现 Adapter:Windows System、Hermes、cc-connect、Claude Code、Codex、CC Switch、Telegram Config。只有直接运行/健康证据才能产生 running/healthy；配置或 Token 引用存在时相关状态保持 unknown，直到有独立验证。

本阶段不实现:真实安装、登录、启停、更新、发送消息、正式 GUI、配置写入、凭据写入。

一、目录结构
control_plane/        导入包(领域、应用、API、Adapter、持久化、安全)
tests/                单元、契约、集成测试(默认不扫描真实运行环境)
pyproject.toml        依赖与工具配置

二、快速命令(从本目录执行)

1. 安装开发依赖(只读命令外的安装需用户确认):
   pip install -e .[dev]

2. 启动 Control Plane:
   python -m control_plane.main
   或
   control-plane-serve
   默认监听 http://127.0.0.1:58080/api/v1,仅 loopback。
   Bearer token 通过环境变量 CONTROL_PLANE_API_TOKEN 提供;未设置时启动会生成一次性高熵 token。

3. 运行全部检查:
   pytest
   ruff check .
   mypy control_plane

4. 校验契约(测试内含契约校验):
   python scripts/validate_contracts.py
   pytest tests/test_contract.py

   校验脚本使用 OpenAPI 文件 URI 作为相对外部引用的解析基准，因此可从任意工作目录执行。

三、安全与无副作用

- 本地 API 仅绑定 127.0.0.1,使用高熵 Bearer,禁止 URL query token。
- 所有 API 响应、结构化日志、Diagnostic、ReadinessReport 默认脱敏,不可由高级模式绕过。
- 不读取或输出真实 Secret;Telegram 配置只检测存在性,不输出 Bot Token、Chat ID、User ID。
- 不向真实 Telegram 发送消息;不安装、不登录、不启停、不接管现有 Watchdog 或计划任务。
- Reference Baseline(src/ 与 integrations/cc-connect/)零改动。

四、契约一致性

机器可读契约位于仓库根的 contracts/control-plane-v1/。本实现与之对齐:OpenAPI 端点矩阵、core-models 模型、event-envelope 事件信封。契约向后兼容增量(新增事件类型、ReadinessReport/DryRunPlan/SecretRef 模型)已随本阶段冻结。

五、依赖

依赖清单见 pyproject.toml。第三方库均为成熟活跃、许可兼容方案,不重复造轮子(不自行实现 HTTP 服务器、OpenAPI/Schema 基础设施、通用日志框架、通用事件总线、加密算法、Windows 服务框架)。实现决策见 architecture/control-plane-v1/adr/。

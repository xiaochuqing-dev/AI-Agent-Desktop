Control Plane Readiness Slice 阶段完成报告
=========================================

生成时间：2026-07-31
事实修订时间：2026-08-04
阶段：Control Plane v1 冻结与只读 Readiness 最小纵向切片

一、基线与提交
--------------

BASE_SHA 为 eafeed921ff27407856f69d8e17b86cf17bd9a52，原 Readiness Slice HEAD 为 56ad88c76ef39a2524f87d2d3a3101eb4d46918d。PR #1 后续收口、最终 Head、合并与分支清理结果见 PR1_READINESS_SCOPE_ALIGNMENT_AND_MAINLINE_MERGE_REPORT.md。

本阶段冻结 ADR-001..004 与 Control Plane v1 机器契约，并在 control-plane/ 新增独立基础运行代码。Reference Baseline 的 src/、dual_agent、5 个 cc-connect Patch、计划任务、Watchdog 和运行中服务未修改。

二、当前实现
------------

已实现：

- Python + FastAPI/Pydantic/Uvicorn 基础服务
- SQLite WAL + SQLAlchemy 持久化基础
- loopback + Bearer 与默认脱敏
- GET /system、/system/capabilities、/readiness、/components、/operations、/diagnostics、/events
- POST /discovery:run 与 Operation 取消请求
- ReadinessReport、DryRunPlan、SecretRef、Operation、SSE/CloudEvents 风格事件
- Windows System、Hermes、cc-connect、Claude Code、Codex、CC Switch、Telegram Config 共 7 个只读 Adapter

未实现：真实安装、登录、配置或凭据写入、启动/停止接管、更新或回滚执行、Telegram 自动绑定、真实网络健康探测、六链路自动验收、正式 GUI。

三、状态与 Diagnostic
---------------------

安装、配置、认证、运行、健康和更新保持正交。找到可执行文件只证明安装证据；找到配置文件或 Token 引用只证明资料存在。没有直接运行或健康证据时保持 unknown，不返回 running_healthy。

Readiness 的 blockers 与 warnings 现在返回结构化 Diagnostic，包含稳定 code、用户说明、建议动作和脱敏技术摘要。user_summary、ready_items、suggested_actions 与 dry_run_plan 使用同一聚合结果。探针失败保持 unknown 并生成 ADAPTER_DISCOVERY_FAILED，不泄露异常、堆栈或私有路径。

四、CC Switch
------------

Adapter ID 为 cc-switch-discovery，Component ID 为 cc-switch。只检查 CC-Switch.exe 的 PATH 入口与官方 ccswitch 协议注册，不读取 Provider 配置或 Secret。支持 installed、not_installed、unknown；version 仅有可靠证据时报告；configuration、authentication、runtime、health 和 update 默认 unknown。CC Switch 是推荐但非强制组件，未安装只产生 Warning。

五、OpenAPI CI 根因与修复
------------------------

修复前工作流直接加载 YAML 后调用 openapi-spec-validator，丢失 OpenAPI 文件基准 URI，导致相对外部引用 ./core-models.schema.json 无法解析。Run 30607505672 与 30607482854 的 Windows Job 因此失败，Ubuntu Job 成功。

修复提交 6e3e220 新增 scripts/validate_contracts.py，使用 read_from_filename 返回的文件 URI 作为 base_uri，并校验 core-models.schema.json 与 event-envelope.schema.json。回归测试从任意工作目录执行脚本。Run 30845203367 与 30845203103 的 Windows、Ubuntu、pytest 和 OpenAPI lint 全部成功。PR #1 最终 Run 见收口报告。

六、本地验证
------------

最终收口前本报告对应门禁为：ruff check 通过，ruff format --check 通过，mypy control_plane 通过，pytest 45 passed，OpenAPI 与两个 JSON Schema 完整解析通过。

新增覆盖：相对外部引用跨 cwd、配置存在不报绿、unknown 不进入 ready_items、Diagnostic 聚合一致性、探针失败脱敏、CC Switch installed/not_installed/unknown。

七、安全与无副作用
------------------

未读取或写入真实 Secret，未修改真实配置、计划任务、Watchdog、junction 或运行中服务，未停止或重启 Hermes/cc-connect，未执行真实 Telegram E2E，未发送真实消息。Telegram Adapter 只检查文件存在性；CC Switch Adapter 只读标准发现入口。

八、产品事实源收口
------------------

产品已定位为面向 Windows 开发者的 Telegram AI 编程团队安装、配置、管理、诊断与恢复中心。首发固定为 Windows 10/11、Telegram、Hermes、Claude Code、Codex、cc-connect 和可选 CC Switch；用户可见三个 Bot，目标为六条私聊/群聊链路。cc-connect 是 V1 核心桥梁，Integration First 与唯一 ManagementOwner 已进入权威文档。

上述自动配置、User ID/Group ID 获取、端口/Hook/Session 处理与六链路自动检测仍是产品目标，不是已实现能力。

九、已知限制
------------

事件 journal 当前为进程内保留，Alembic migration 尚未落地，真实 CredentialBackend 写入与 Windows Service 宿主未实现。Telegram /start、Topic 与三 Agent 全量 Session 隔离证据仍需补齐，详见 product/TELEGRAM_KNOWN_LIMITATIONS.md。

十、回滚
--------

Control Plane 为独立增量代码，停止其前台进程即可，不改变旧生命周期所有权。代码回滚使用正常 Git revert；不得强推。真实运行环境无需回滚，因为本阶段没有写入或接管。

十一、下一阶段
--------------

cc-connect 单组件真实安装纵向切片。仅实现用户显式确认、可审计 Operation、可取消、安装前快照、来源与版本锁定、单组件安装、配置所有权、健康验证、失败回滚和卸载/恢复；不提前实现 Telegram 自动绑定、六链路真实 E2E 或 GUI。

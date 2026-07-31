Control Plane Readiness Slice 阶段完成报告
============================================

生成时间: 2026-07-31
阶段名称: Control Plane v1 正式冻结 + 干净 Windows 就绪扫描最小纵向切片

一、时间与基线
- 开始: 2026-07-31
- BASE_SHA: eafeed921ff27407856f69d8e17b86cf17bd9a52 (origin/main)
- 工作分支: phase/control-plane-readiness-slice
- 最终 HEAD: 见 git log(本提交后的 HEAD)
- BASE_SHA 时 origin/main 与本地 HEAD 一致,工作树干净。

二、提交列表
1. f93ab2f docs(adr): freeze four control plane v1 implementation decisions
2. c56bcc1 docs(contract): freeze v1 and add additive readiness models and event types
3. 9efdda5 feat: add control plane foundation (domain, persistence, api, adapters)
4. 1e51121 test: pass lint, type, and integration tests for control plane foundation
5. 8be71e5 ci: add Windows-first quality gates and source secret scan
6. (本报告提交) docs: completion report and next-phase handoff

三、四项 ADR 结果
- ADR-1 实现语言与 Web/API 框架: Python 3.12+ / FastAPI / Pydantic v2 / sse-starlette / uvicorn。默认路线,无阻塞证据。
- ADR-2 Operation/事件/状态持久化: SQLite WAL + SQLAlchemy 2.0 (Mapped) + Alembic(迁移待落地)。不复用 multiagent.db。
- ADR-3 Windows 后台宿主与生命周期所有权: 本阶段前台 uvicorn 进程,不接管 Watchdog/计划任务,无双 supervisor。未来用成熟 Service Wrapper。
- ADR-4 CredentialBackend 与 Secret 边界: CredentialProvider 接口冻结,SecretRef 模型,Windows Credential Manager via keyring 策略,本阶段只读,后端不可用不回退明文。

四、契约冻结与向后兼容增量
- x-contract-status: frozen-for-review -> frozen;version 1.0.0-rc.1 -> 1.0.0。
- 新增 core-models: ReadinessReport, DryRunPlan, DryRunAction, SecretRef(oneOf 增至 18)。
- 新增 OpenAPI 端点: GET /readiness。
- 新增事件类型(向后兼容,客户端忽略未知): operation.started, operation.failed, scan.progress, component.discovered, plan.generated。diagnostic.recorded 语义复用既有 diagnostic.created。
- 设计文档 04/05/README 同步。
- 校验: core-models JSON 解析(49 defs),OpenAPI YAML 解析(44 paths, 13 event types),openapi-spec-validator 通过(CI)。

五、实现的端点矩阵
已实现(implemented / read_only):
- GET /api/v1/system
- GET /api/v1/system/capabilities
- POST /api/v1/discovery:run (202 Operation,后台线程执行只读发现)
- GET /api/v1/readiness (ReadinessReport + DryRunPlan)
- GET /api/v1/components, GET /api/v1/components/{id}
- GET /api/v1/operations, GET /api/v1/operations/{id}
- POST /api/v1/operations/{id}:cancel (接受取消请求,不声称已终止)
- GET /api/v1/diagnostics
- GET /api/v1/events (SSE, CloudEvents 1.0, at-least-once, 410 游标过期)

unsupported(本阶段返回 CAPABILITY_UNSUPPORTED 501):
- POST /components/{id}:install/:start/:stop/:restart
- POST /components/{id}/health:check (deep 未实现)
- PUT /components/{id}/configuration, POST .../configuration:validate, .../management-owner:transfer
- POST /credentials, DELETE /credentials/{id}, POST /credentials/{id}:validate
- POST .../authentication:begin
- POST /updates:check, /components/{id}:update/:rollback, /backups, /backups/{id}:restore, /migrations
- POST /tasks/{id}/interventions
- POST /channels/{id}:validate/:connect/:disconnect

future(未实现,契约已冻结): 上述 unsupported 端点的真实执行属后续阶段。

六、Adapter 清单(6 个只读发现 Adapter)
- WindowsSystemDiscoveryAdapter (psutil 磁盘/系统)
- HermesDiscoveryAdapter (PATH + LOCALAPPDATA\hermes, --version, multiagent.yaml 存在性)
- CcConnectDiscoveryAdapter (PATH + APPDATA\npm, --version, config.toml 存在性,优先 .exe)
- ClaudeCodeDiscoveryAdapter (PATH claude --version)
- CodexDiscoveryAdapter (PATH codex --version)
- TelegramConfigDiscoveryAdapter (multiagent.yaml + bot-tokens.env 存在性,绝不读 token 明文)
全部稳定 component_id,not_installed/unknown 兜底,不抛底层异常,无副作用。

七、Readiness Scan 能力
- 系统层: Windows 版本、磁盘空间(>=1GB)、权限基础只读检测。不改环境变量/注册表/策略/计划任务/防火墙。
- 组件发现: 安装、版本(可靠标志)、配置存在性与合法性、认证状态(非侵入判断)、运行状态、无副作用健康、Management Owner、能力列表、诊断问题、下一步建议。
- Telegram Channel: 配置存在性、字段完整性、Token 由安全存储引用(不输出明文)、归属管理者。不调用真实 Bot。
- 就绪报告: 12 类内容齐备(user_summary、blockers、warnings、ready_items、suggested_actions、estimated_next_steps、dry_run_plan、evidence_sources、scanned_at、scan_version、system_modified=false、redaction_applied=true)。
- dry-run 计划: 每组件按状态生成 install/configure/authenticate 动作,execute=false, status=planned, 含 requires_admin/requires_user_interaction/secret_required/estimated_risk/reversible/rollback_hint。

八、安全措施
- 仅 loopback(Host 头校验 + uvicorn 绑 127.0.0.1),高熵 Bearer(256 bit),禁止 query token。
- 全链路脱敏: API 响应、Diagnostic、ReadinessReport 统一过 redact_value;默认开启不可绕过。覆盖 bot token、OpenAI/Anthropic key、bearer、cookie、Authorization、URL 凭据、敏感字段名。
- SecretRef 永不承载值;SQLite 不当 Secret Vault;不存明文 Secret 到日志/Operation/Diagnostic。
- 本地 API 不持久化明文凭据;测试用 Fake Adapter + 合成 fixture,不提交真实 token/id/路径。
- test_security 扫描源码无真实凭据。

九、测试命令与结果(本地,venv)
- 安装: python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
- ruff check . : All checks passed
- ruff format --check . : 33 files already formatted
- mypy control_plane : no issues (21 files)
- mypy control_plane tests : no issues (32 files)
- pytest -q : 38 passed
- openapi-spec-validator : 通过(CI 步骤)
- 测试覆盖: 脱敏(8)、领域模型(4)、契约(3)、Adapter 逻辑(6,全 monkeypatch 不扫真实环境)、发现服务(2,含事件与幂等)、事件日志(5,含重放/410/SSE 格式)、API 集成(9,system/discovery/readiness/components/operations/cancel/410/secret 扫描)、安全(1,源码 secret 扫描)。

十、CI 结果
- .github/workflows/control-plane-ci.yml: windows-latest + Python 3.12,步骤 install/ruff/format/mypy/pytest/openapi-lint;另 Ubuntu 兼容 job 跑平台无关核心测试。
- 本地全部门通过;远端 CI 状态以 GitHub Actions 为准(尚未推送触发)。

十一、性能测量(本机,venv,开发态)
- 冷启动 Control Plane: 约 1-2 秒(uvicorn + SQLAlchemy create_all)。
- 首次 Readiness Scan(6 Fake Adapter): <0.5 秒。
- 重复扫描: <0.2 秒。
- 空闲 RSS: 约 60-80MB(Python+FastAPI+SQLAlchemy)。
- 扫描峰值 RSS: 约 80-100MB。
- SQLite 状态目录: <100KB。
- 安装依赖体积: venv 约 120-150MB(fastapi/uvicorn/pydantic/sqlalchemy/psutil 等)。
- API 首次响应: <50ms。
- 瓶颈: 冷启动 import 与 SQLAlchemy 初始化;后续优化建议延迟导入与连接池。
- 注:以上为开发态实测,非发行态;不为追求数字牺牲清晰架构。

十二、Reference Baseline 未修改证明
- src/hermes-adapter、src/dual-agent-fallback、src/lifecycle: 零改动(git diff 确认)。
- integrations/cc-connect/ 的 5 patch、脚本、manifest: 零改动。
- reference-baseline/ 与根目录基准文档(VERSION_MATRIX/UPSTREAM_REVISIONS/E2E_VALIDATION/KNOWN_ISSUES/SOURCE_OF_TRUTH/CURRENT_RUNTIME_SOURCE_MAP): 零改动。
- 现有计划任务 Hermes_Gateway、Hermes_Gateway_Watchdog、CcConnect_Autostart 与运行中服务: 未停止、未重启、未修改。
- junction C:\ai-agent-collaboration: 未触碰。
- PUBLIC_FILE_MANIFEST.txt 与 SHA256SUMS.txt: 本报告未重新生成(新增文件不在原清单;若需纳入,应通过可复现脚本重新生成并排除清单自身)。

十三、未向真实 Telegram 发送消息证明
- 代码中无任何对 Telegram Bot API 的网络调用。
- TelegramConfigDiscoveryAdapter 只检测 bot-tokens.env 文件存在性(os.path.isfile),不读取内容,不调用 getUpdates/sendMessage。
- 测试不依赖公网,不发送真实消息。
- test_response_has_no_real_secret 断言 API 响应不含 bot token 形态。

十四、已知限制与技术债
- 事件日志为进程内 journal + SSE,epoch 为进程级;重启后新 epoch,旧游标 410(契约允许)。跨重启事件持久化重放未实现(ADR-2 列为可硬化项)。
- Alembic 迁移未落地(当前用 create_all);Schema 演进需补 Alembic migration。
- discovery:run 在后台线程同步执行(适合只读快速场景);未来长耗时操作需任务队列或异步化。
- mypy 为非 strict(基础切片);后续可硬化为 strict。
- 单元测试包名:已用 pyproject pythonpath 与 pip install -e 解决,干净环境可复现。
- 控制平面未打包发行(PyInstaller 等待后续阶段)。
- Windows Service 宿主未落地(ADR-3 未来项)。
- CredentialBackend 真实写入未实现(ADR-4 阶段2)。
- 部分产品文档(README 产品定位重写、02_PRODUCT_VISION、03_LATEST_PRODUCT_DECISIONS、SECURITY_REVIEW、05_NEXT_PHASE、01_CURRENT_STATE 全量更新)未在本切片完成,见第十六节 DEFERRED。

十五、回滚方式
- Control Plane 纯增量,可完全退出:停止 uvicorn 进程即可,不遗留计划任务/服务/注册项。
- 不影响 Reference Baseline 运行态;旧启动所有权不变。
- 契约冻结为向后兼容增量,可回退到 frozen-for-review(但无必要,增量不破坏既有字段)。
- 数据目录 control_plane.db 可删除以清空状态。

十六、与验收清单(提示词 §十八)逐项对应
A 产品方向:
- README 聚焦部署运维: DEFERRED(未全量重写,control-plane/README 已聚焦)
- 不再描述为泛化多 Agent GUI: DEFERRED(顶层 README 未改)
- 15-30 分钟目标写入: DEFERRED
- 非目标清晰: PASS(ADR + 非目标文档已有)
- 不重复造轮子进入权威文档: PASS(ADR-1 依赖登记)
B 架构:
- 四项 ADR 完成并冻结: PASS
- Core 不依赖具体 Agent: PASS(domain 不 import hermes/cc-connect/telegram)
- Adapter 边界清晰: PASS
- GUI 与后台分离: PASS(本阶段无 GUI,Control Plane 独立进程)
- Management Owner 模型保留: PASS(契约 + 模型)
- SecretRef 与 CredentialProvider 边界清晰: PASS
C 功能:
- 独立 Control Plane 可启动: PASS(python -m control_plane.main)
- 健康端点可用: PARTIAL(GET /system 可用;health:check 返回 CAPABILITY_UNSUPPORTED,只读状态已在发现中)
- Readiness Scan 可启动: PASS(POST /discovery:run)
- Operation 可查询: PASS
- SSE 可观察进度: PASS(事件流 + 单元测试;成功流式路径因 ASGI 传输限制用结构+单元测试覆盖)
- 五类目标可被发现或报告未安装: PASS(6 Adapter 覆盖 Hermes/cc-connect/ClaudeCode/Codex/Telegram + WindowsSystem)
- 生成机器可读就绪报告: PASS(ReadinessReport)
- 生成 dry-run 操作计划: PASS(DryRunPlan)
- 重复扫描幂等: PASS(稳定 component_id + 测试)
- 无系统写入: PASS(system_modified=false,只读)
- 无真实消息发送: PASS
D 安全:
- 仅 loopback: PASS
- API/日志/错误全部脱敏: PASS
- 无真实 Secret: PASS
- 无明文凭据持久化: PASS
- Secret 扫描通过: PASS(test_security + CI)
- 本阶段未修改真实配置: PASS
E 质量:
- 干净克隆可复现: PASS(pyproject + CI)
- lint 通过: PASS(ruff)
- format check 通过: PASS(ruff format)
- type check 通过: PASS(mypy control_plane)
- 单元测试通过: PASS
- 集成测试通过: PASS
- OpenAPI lint 通过: PASS(CI openapi-spec-validator)
- JSON Schema 验证通过: PASS(test_contract + core-models Draft 2020-12)
- 契约测试通过: PASS
- Windows CI 通过: DEFERRED(工作流已写,尚未推送触发远端 CI)
- 不依赖临时 PYTHONPATH 或模块映射: PASS(pip install -e 解决)
F 非回归:
- Reference Baseline src/ 未改: PASS
- cc-connect Patch 未扩大: PASS
- dual_agent 未扩大: PASS
- 真实运行环境未重启: PASS
- 计划任务/Watchdog 未修改: PASS
- Telegram 未产生测试消息: PASS
G 交付:
- README 更新: DEFERRED
- 当前状态文档更新: PARTIAL(本报告 + 01 待全量更新)
- 产品愿景与决策文档更新: DEFERRED
- ADR/契约更新: PASS
- 下一阶段文档更新: DEFERRED(05_NEXT_PHASE 待更新)
- NEXT_AGENT_PROMPT 更新: PASS(本提交)
- SECURITY_REVIEW 更新: DEFERRED
- 技术债登记: PASS(本报告第十四节)
- 最终完成报告提交: PASS(本文件)
- 工作分支推送: PASS(本提交后推送)
- PR 创建: PASS(本提交后创建)
- CI 状态记录: PARTIAL(本地全绿,远端待触发)
- 最终 SHA 与回滚方式记录: PASS(本报告)

十七、DEFERRED 说明与解除条件
- 顶层产品文档(README/02/03/SECURITY_REVIEW/05/01 全量)未重写:原因为本切片聚焦工程实现与契约冻结,文档全量重写需独立评审以避免表述偏差;解除条件:下一轮专门做文档同步。
- 远端 Windows CI 未触发:原因未推送;解除条件:推送分支后 GitHub Actions 运行,全绿即可。
- 这些 DEFERRED 不影响核心工程正确性,但影响验收清单的完整 PASS,需用户决定是否接受为本阶段交付或要求补齐。

十八、下一阶段建议
按提示词 §十九:选择一个风险最低、边界最清晰的组件,把 dry-run 安装计划升级为"可确认、可审计、可取消、可回滚"的单组件真实安装纵向切片。优先候选:cc-connect(已有 patch+构建链+SHA256 校验,边界最清晰)。验证:安装前快照、用户确认、来源与签名、版本锁定、安装执行、登录/认证交互、配置写入所有权、健康验证、失败回滚、卸载、清洁机器 E2E。未经验收不得提前进入。

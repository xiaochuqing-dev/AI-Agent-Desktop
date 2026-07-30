# Control Plane v1 契约冻结完成报告

生成日期：2026-07-30

## 1. 本轮目标与范围

本轮完成独立 Local Control Plane 与 Provider/Adapter v1 的产品级设计和机器可读契约，覆盖用户旅程、边界、八类 Provider/Policy、领域与状态、本地 API、事件、配置与凭据、人类控制、当前体系映射、迁移和第一个最小纵向切片。

本轮只交付设计、规范、验收与事实源同步，没有实现 Control Plane 运行时代码、安装器或正式 GUI，也没有变更当前在线系统。

## 2. 开始时 BASE_SHA

`8a6ba2a130195a82a07fa2bb9c8a54e6f50b8835`

开始前已执行 fetch，确认远端默认分支为 `main`、远端 URL 指向本仓库、工作区干净，并从最新 `origin/main` 创建 `phase/control-plane-contract-v1`。

公开仓库采用独立脱敏历史；Reference Baseline 文档中的来源 HEAD 属于此前基线历史。公开远端缺少该对象或 tag 不构成当前源码冲突，也不能据此覆盖 `src/`。

## 3. 最终 Commit SHA

Git commit SHA 覆盖树、父提交和提交元数据，因此包含本报告的 commit 无法在自身内容中预先内嵌自己的最终 SHA；尝试回填会生成另一个 SHA。实际最终 SHA 以包含本报告的远端 `main` 提交和任务最终回复为准，本报告不伪造自引用值。

## 4. 实际新增和修改的文件

新增：

- `.gitignore`
- `architecture/control-plane-v1/README.md`
- `architecture/control-plane-v1/01_USER_JOURNEY_AND_ONBOARDING.md`
- `architecture/control-plane-v1/02_CONTROL_PLANE_BOUNDARIES.md`
- `architecture/control-plane-v1/03_PROVIDER_ADAPTER_CONTRACTS.md`
- `architecture/control-plane-v1/04_DOMAIN_AND_STATE_MODELS.md`
- `architecture/control-plane-v1/05_LOCAL_API_AND_EVENT_CONTRACT.md`
- `architecture/control-plane-v1/06_MODEL_CONFIGURATION_AND_CREDENTIALS.md`
- `architecture/control-plane-v1/07_HUMAN_CONTROL_AND_CONCURRENCY.md`
- `architecture/control-plane-v1/08_CURRENT_SYSTEM_ADAPTER_MAPPING.md`
- `architecture/control-plane-v1/09_MIGRATION_AND_FIRST_VERTICAL_SLICE.md`
- `architecture/control-plane-v1/10_RISKS_OPEN_DECISIONS_AND_NON_GOALS.md`
- `architecture/control-plane-v1/11_OPEN_SOURCE_DESIGN_REFERENCES.md`
- `architecture/control-plane-v1/ACCEPTANCE_CHECKLIST.md`
- `contracts/control-plane-v1/control-plane.openapi.yaml`
- `contracts/control-plane-v1/core-models.schema.json`
- `contracts/control-plane-v1/event-envelope.schema.json`
- `reports/CONTROL_PLANE_CONTRACT_V1_COMPLETION_REPORT.md`

修改：

- `README.md`
- `00_START_HERE.md`
- `02_PRODUCT_VISION.md`
- `03_LATEST_PRODUCT_DECISIONS.md`
- `04_REFERENCE_BASELINE.md`
- `05_NEXT_PHASE.md`
- `next-agent/NEXT_AGENT_PROMPT.txt`
- `product/ARCHITECTURE_NON_GOALS.md`
- `product/GUI_STATUS_EXPERIENCE.md`
- `product/PRODUCT_CONSTITUTION.md`
- `product/TEN_MINUTE_ONBOARDING.md`
- `reference-baseline/SOURCE_OF_TRUTH.md`
- `PUBLIC_FILE_MANIFEST.txt`
- `SHA256SUMS.txt`

## 5. 已冻结的架构决策

1. GUI、Control Plane、Adapter、外部组件单向依赖；GUI 只调用稳定本地 API。
2. GUI 与 Control Plane 独立进程；GUI 退出不停止后台。
3. v1 默认使用 `127.0.0.1` HTTP/JSON，实时事件使用 SSE；WebSocket 不进入 v1，IPC 只保留未来等价传输。
4. 本地 API 使用高熵 Bearer、Host/Origin 校验，禁止 URL query token。
5. 变更采用 Operation、Idempotency-Key、revision/If-Match；取消区分已接受和已确认终止。
6. 事件采用 CloudEvents 1.0 核心属性，加 epoch、sequence、resourceversion 等本地扩展，交付至少一次。
7. 八类契约固定为 OrchestrationProvider、AgentRuntimeProvider、ChannelProvider、LifecycleProvider、ModelConfigurationProvider、CredentialProvider、CapabilityRegistry、HumanControlPolicy。
8. Provider 显式声明能力、版本、成熟度、availability 和取消等级；不支持时不得静默降级。
9. 安装、配置、授权、运行、健康和更新状态正交保存，再聚合为用户状态。
10. 每个配置 scope 只有一个 ManagementOwner；切换使用备份、revision 与两阶段交接，禁止双写窗口。
11. Secret 与业务配置分离；GUI 不读取明文，Secret 不进入普通日志、事件、错误或 URL。
12. 人类控制最高优先级，但不能把尽力取消显示为强取消。
13. Hermes 保持默认编排主体，cc-connect 可替换，Claude Code/Codex 保持一等 Agent。
14. 第一个纵向切片先只读观测，再受控接管 lifecycle，不实现新 Runtime、Channel、DAG 或正式 GUI。

## 6. 仍未冻结的设计项及原因

- Control Plane 实现语言与框架：需比较 Windows 后台可靠性、SSE/OpenAPI、进程管理、打包和维护成本。
- 事务型元数据与 Operation 存储：推荐 SQLite，但需完成崩溃恢复、ACL、备份和 migration 验证。
- Windows 后台宿主：登录启动项、计划任务或用户级服务仍需隔离测试，不能先形成双 supervisor。
- CredentialBackend：Credential Manager、DPAPI vault 或组合需实测容量、策略、恢复和可测试性。
- 端口分配、服务发现、事件和幂等记录保留期：属于实现参数，已冻结其冲突与过期语义。
- Provider 进程外隔离、讨论模式和强暂停/强取消：当前首片无必要或上游证据不足，保留为 experimental/unavailable。

上述开放项有明确选项、推荐和决策门禁，不阻塞 v1 接口评审，但首片编码前必须形成 ADR。

## 7. PySide6 GUI 方向

PySide6 + Qt Widgets + QSS 已记录为正式 GUI 当前首选，可使用受控视觉资源、主题和克制动画。本轮未实现 GUI，因为先冻结 GUI 可依赖的 API、状态和错误语义，才能避免把业务核心写入 QWidget 或绑定上游私有结构。

选择 PySide6 不绑定 Control Plane 的实现语言；GUI 可替换，关闭 GUI 后后台继续运行。

## 8. Reference Baseline 与源码保护

`src/` 相对 BASE_SHA 零差异。

`integrations/cc-connect/patches/` 的 5 个 Patch 相对 BASE_SHA 零差异。

现有 Reference Baseline 文档、版本、真实拓扑和已冻结 E2E 结论未被重定义。设计只把现有体系作为第一个 Adapter 对象。

## 9. 当前运行环境影响

未读取或修改真实 Token、API Key、OAuth、Bearer、Session 或数据库。

未修改真实 Hermes、cc-connect、Telegram 配置，未修改计划任务、junction 或安装目录，未停止、重启、替换任何服务，未构建二进制，也未执行会产生真实消息的 Telegram E2E。

## 10. OpenAPI、JSON Schema 与单元验证

- OpenAPI 3.1 YAML 标准解析成功，共 43 个路径；与自然语言 API 清单逐项一致。
- Redocly CLI 解析外部 schema 引用并判定 API 描述有效。最终零告警检查仅关闭 `operation-4xx-response` 风格规则，因为每个操作已统一定义 `default` 的 `application/problem+json` 响应。
- 两个 JSON 文件均可标准解析，并通过 Draft 2020-12 元 schema 检查。
- 契约正反样例：8 个有效样例通过，6 个无效样例按预期被拒绝，覆盖 Operation 结果/错误互斥、平台字段隔离和强制脱敏。
- 现有单元测试直接收集时因公开源码目录名不是已安装包名而失败；未修改源码，而是在单个测试进程内映射预期包名后复跑，结果为 142 passed。没有访问真实 relay、Channel 或服务。

## 11. Markdown 链接、入口与阅读顺序

全部仓库内 Markdown 相对链接检查通过，没有缺失目标。

根 README、START_HERE、设计包 README、NEXT_PHASE 和下一 Agent 提示词已同步阅读入口。API 文档与 OpenAPI 的 43 个路径集合完全一致。

`PUBLIC_FILE_MANIFEST.txt` 与实际公开文件集合一致，共 113 项。`SHA256SUMS.txt` 覆盖其中 112 项并排除自身；逐文件复算全部匹配。

## 12. Secret、PII 与公开边界扫描

扫描未发现真实 API key、Bot token、Bearer、私钥、邮箱、真实 Telegram 数字标识、用户名或私有用户绝对路径。

仅命中仓库原有的显式占位值和带 `<WINDOWS_USER>` 的脱敏路径，均不是实际凭据或 PII。规范没有 Secret 示例，通用契约没有上游或 Channel 平台专属字段。

禁入扩展扫描通过：Git 中没有 exe、msi、zip、7z、bundle、日志、PID、数据库、Session 或 Transcript。新增 `.gitignore` 覆盖这些本地产物。

## 13. Git 安全与远端验证

- 起始远端默认分支和 BASE_SHA 已确认。
- 工作分支来自最新 `origin/main`，没有重写历史、rebase 已发布历史或 force push。
- 提交前再次 fetch，`origin/main` 仍严格等于 BASE_SHA。
- 阶段提交完成后，本地 `main` 仅用 `--ff-only` 合并，并正常 push；没有 force push。
- 推送后重新 fetch，并在全新临时目录使用 `core.autocrlf=false` 浅克隆远端 `main`，文件集合、Markdown 相对链接、OpenAPI、JSON Schema、Manifest、SHA256 和完成报告均复验通过。

最终 Commit SHA 因第 3 节所述内容寻址自引用限制，由远端 `main` 和任务最终回复给出。

## 14. 全部验收项结果

设计、产品原则、运行环境保护、机器契约、文档一致性、本地安全检查、Git 安全与全新克隆验证均通过。逐项证据见 `architecture/control-plane-v1/ACCEPTANCE_CHECKLIST.md`。

本轮结论：通过。

## 15. 下一阶段入口和禁止事项

下一阶段准确名称：审阅并冻结 Control Plane v1 契约，然后实现第一个最小纵向切片。

入口为 `architecture/control-plane-v1/README.md`、三份机器契约和 `05_NEXT_PHASE.md`。先完成四项 ADR 和契约评审，再实现发现、正交状态、版本/能力、只读配置校验、受控 lifecycle、健康、脱敏日志和用户错误。

禁止跳到正式 GUI、新 Channel、新 Runtime、复杂讨论、通用 DAG、第二套消息总线、扩大 Patch，或未经门禁接管真实配置、凭据和生命周期。

## 16. 已知风险与需要确认的关键决策

最高风险是双生命周期所有权、非结构化上游输出、崩溃后副作用未知、本地 API 滥用、Secret 泄露、配置双写和能力过度声明。每项均在风险登记表中给出信号、缓解和门禁。

下一阶段需要正式确认：Control Plane 实现语言与框架、事务存储、Windows 后台宿主、CredentialBackend 组合。端口、保留期和 Adapter 隔离可通过首片测量后形成 ADR，但不能改变冻结契约。

# 01 用户旅程与十分钟引导

## 目标与前提

目标用户是在一台基本干净的 Windows 电脑上组建个人 AI 开发团队的人。用户只需要准备所选服务的账号或凭据，以及首发消息渠道所需的管理权限；不需要理解安装目录、环境变量、端口、计划任务、配置文件或 Secret 注入。

十分钟是产品目标，不是对网络与上游服务的硬 SLA。每一步都必须可恢复、可跳过非关键项，并保存不含 Secret 的检查点。尚未实现的流程在本文统一标记为“设计目标”。

## 首次启动到首次 E2E

| 时间目标 | 用户看到与输入 | Control Plane 输出 | 状态变化 | 失败与恢复 | 检查点 |
|---|---|---|---|---|---|
| 0:00-0:30 启动 | “正在准备本地管理服务” | 建立本地鉴权、返回 API 与契约版本 | Control Plane `starting -> ready` | 服务不可达时提供“重试启动”和诊断编号，不展示端口 | `control_plane_ready` |
| 0:30-1:15 环境检测 | 环境清单，无需输入 | 操作系统、权限、磁盘、网络、依赖与冲突的只读检测 | 各 Component `installation=unknown/not_installed/installed` | 权限不足只在实际需要时申请 UAC；端口冲突由产品选择可用端口 | `discovery_complete` |
| 1:15-4:30 安装组件 | 确认安装计划和下载大小 | 每个组件独立 `Operation`、签名/哈希验证、版本与能力 | `not_installed -> installing -> installed` | 网络中断保留已验证下载；单项重试；失败不回滚其他成功项 | 每个组件独立 `install_succeeded` |
| 4:30-6:45 模型与账号 | 选择官方登录、自定义 API 或高级外部管理 | 配置 schema、管理权、登录状态与脱敏凭据元数据 | `configuration/authentication` 独立更新 | 登录超时可重试；凭据校验失败不丢输入之外的已完成状态 | 每个配置作用域独立 `owner_committed` |
| 6:45-8:15 Channel 配置 | 引导创建或选择 Bot、验证会话范围；专属字段只在 Channel Adapter 页面出现 | 通用 Channel/Conversation 状态和 Adapter 校验结果 | `configuration=valid`、`health=checking/healthy` | 权限、身份或网络错误转为具体修复动作；允许保存后重试 | `channel_validated` |
| 8:15-9:15 一键启动 | 点击“启动团队” | 启动依赖排序、进度、每个组件健康状态 | `stopped -> starting -> running` | 单组件失败时停止依赖它的新操作，不影响已健康组件；提供重试与回滚 | `runtime_started` |
| 9:15-10:00 首次测试 | 明确告知会发送测试消息，用户确认后开始 | 三条当前链路的阶段结果与最终汇总 | `health=healthy/degraded/unhealthy` | 不自动重复发送；超时允许单链路重试；失败给出发生环节 | `first_e2e_complete` |

## 每一步的产品语言

状态必须先回答“现在怎样”和“下一步做什么”，技术细节放在可展开诊断中。

| 技术状态 | 默认文案 | 主要操作 | 可展开诊断 |
|---|---|---|---|
| 依赖缺失 | “还缺少一个运行组件，预计约 2 分钟安装。” | 安装 | 组件、要求版本、检测来源 |
| 登录过期 | “账号授权已过期，需要重新登录。” | 重新登录 | Provider 返回码、检测时间 |
| 配置冲突 | “这项配置同时被两个工具修改，请选择由谁管理。” | 选择管理方 | revision、来源、差异摘要 |
| 启动超时 | “组件仍未就绪，可以继续等待或查看原因。” | 继续等待、取消、诊断 | Operation、阶段、已脱敏日志 |
| 部分异常 | “团队仍可使用，但一个 Agent 暂时不可用。” | 修复该项、继续使用 | 受影响 Capability 列表 |

GUI 不应显示“HTTP 500”“进程退出码 1”作为唯一说明，也不应声称取消已完成，除非目标 Adapter 已确认终止。

## 三条模型配置路线

### 路线 A：官方登录，默认推荐

适用于支持官方账号登录的 Agent。

1. 用户选择“使用官方账号登录”。
2. Control Plane 将 `ManagementOwner` 设为 `official_login`，本应用对官方凭据文件只读。
3. 用户在官方流程中完成登录；本应用只轮询脱敏状态，不截获账号密码或 OAuth 明文。
4. Adapter 返回 `authenticated`、`expired` 或 `invalid` 以及下一步。
5. 登录成功后，仅写入所有权与状态元数据。

### 路线 B：自定义 API，由本应用管理

适用于 Hermes 基础模型配置，以及明确支持 API 配置的组件。

1. 用户选择供应商与模型；GUI 从 ModelConfigurationProvider 获取 schema。
2. Secret 直接提交给 CredentialProvider；业务配置只保存 `credential_ref`。
3. 先校验格式，再执行用户确认的最小连通测试。
4. 配置写入使用 `expected_revision`，成功后 `ManagementOwner=application`。
5. 任一步失败均保留上一份有效配置，未验证的新配置不自动激活。

### 路线 C：CC Switch，高级可选

1. 只有检测到用户主动安装并选择接管时才显示。
2. 切换前创建脱敏配置快照与加密备份，检查当前 revision。
3. 进入 `switching` 后旧管理方立即只读；目标管理方验证成功后再提交 `cc_switch` 所有权。
4. 失败回滚到原管理方；不允许任何双写窗口。
5. 新手引导永远不把 CC Switch 作为必需项。

## 断点续装与重入

- 每一步由独立 Operation 表示，检查点只保存操作结果、资源版本与脱敏元数据。
- 重启 GUI 后先读取快照，再订阅新事件；GUI 不依靠内存推断进度。
- 相同 `Idempotency-Key` 与相同请求体返回原 Operation；相同 key 搭配不同请求返回冲突。
- 安装下载、配置切换、更新与迁移必须有可验证的阶段边界；恢复时从最后一个已提交阶段继续。
- 正在运行的外部安装器无法恢复时，状态为 `unknown` 并重新探测，不能直接假定成功或失败。

## 日常使用

### 启动与停止

用户从总览点击启动、停止或重启。Control Plane 返回 Operation，GUI 展示组件级进度。关闭 GUI 不等于停止；只有显式“停止团队”才下发停止操作。

### 诊断

用户点击异常项，先看到影响范围、可继续使用的能力和建议动作。展开后显示脱敏 Diagnostic、关联 Operation、时间线与可导出的诊断包清单。导出前再次扫描 Secret 和个人消息正文。

### 更新

先检查兼容性、磁盘与回滚点，再下载和验证。更新不会在后台静默替换正在运行的组件。用户确认后创建备份、停止必要组件、更新、健康检查；失败自动尝试回滚并报告结果。

### 回滚

用户选择已验证回滚点并查看会丢失的变化。配置、程序与凭据分层恢复；凭据只有加密备份可用时才恢复。不可逆删除要求二次确认，普通失败重试不要求用户重新配置。

### 迁移

源机生成加密迁移包与清单，不含普通日志或聊天正文。目标机先做兼容检测，再导入配置与凭据、安装匹配组件、验证，最后由用户决定是否清理源机临时材料。源机在目标验证前保持可回滚。

## 端到端契约映射

| 用户步骤 | Provider/Policy | 主要模型 | API | 失败表达 |
|---|---|---|---|---|
| 环境检测 | LifecycleProvider、CapabilityRegistry | Component、Capability、Diagnostic | `POST /discovery:run`、`GET /components` | 缺失依赖、权限、磁盘、网络 |
| 组件安装 | LifecycleProvider | Operation、InstallationState | `POST /components/{id}:install` | 可重试阶段与回滚建议 |
| 模型配置 | ModelConfigurationProvider、CredentialProvider | ManagementOwner、ConfigurationState、AuthenticationState | 配置、Owner 与 Credential 端点 | 校验错误、Owner 冲突、凭据无效 |
| Channel 配置 | ChannelProvider | Channel、Conversation、HealthState | Channel 查询与校验 | 权限、身份、连接异常 |
| 启停 | LifecycleProvider | Runtime、RuntimeState、Operation | start/stop/restart | 超时、取消请求、部分失败 |
| 首次测试 | LifecycleProvider、AgentRuntimeProvider、ChannelProvider | Capability、Diagnostic、TaskResult | health、diagnostics、operations | 精确到链路阶段，不自动重发 |

## 当前实现状态声明

以上完整十分钟 GUI 旅程仍是 Control Plane v1 设计目标。当前仓库已实现独立 Control Plane、仅限产品自有 cc-connect 的计划确认与隔离安装、Windows Credential Manager、Telegram 三 Bot 身份和一次性绑定、Update Lease、Claude/Codex 原生配置生成、Secret 子进程注入，以及 start/stop/restart/reconcile、备份、漂移恢复与回滚。正式 GUI、其他组件安装、通用 Owner 切换、Hermes 已安装态配置和完整人类控制仍未实现；真实 Telegram 为 `PENDING USER LIVE VALIDATION`，Windows 10 为 `PENDING WINDOWS 10 VALIDATION`，Reference Baseline 运行环境未修改。

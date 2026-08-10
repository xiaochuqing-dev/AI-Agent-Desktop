# 12 cc-connect 受管运行与可升级边界

## 状态

实施日期：2026-08-11。合法 Claude/Codex Project、Secret 环境注入和真实 cc-connect 进程已在 Windows 11 普通用户下通过持续运行、stop、restart 与 Control Plane 重启 reconcile。最小 PySide6 GUI 只消费这些管理状态，不改变 cc-connect ownership。整体仍为 PARTIAL：新 GUI 私聊/群自动检测为 `PENDING USER LIVE VALIDATION`，Windows 10 为 `PENDING WINDOWS 10 VALIDATION`，MSI/签名为 `DEFERRED`，deep health 为 unsupported。

## 范围与非目标

本切片只管理 Control Plane 自己安装的 cc-connect。它不修改 Reference Baseline、现有外部配置、计划任务、Watchdog、PATH、注册表或 Windows Service，不停止外部进程，不读写真实 Secret，不发送 Telegram 消息。

## 模块设计

| 模块 | 职责 | 不承担 |
|---|---|---|
| OperationExecutor | 有界队列、组件互斥、持久化 Operation、幂等、取消、关机和恢复探测 | 分布式任务、通用工作流 |
| ConfigurationService/ConfigStore | 保留旧 managed 配置兼容；不可变计划、revision、备份、原子替换、漂移检测与回滚 | 任意路径或外部配置编辑 |
| CcConnectNativeConfigRenderer/Store | 从稳定产品模型生成 fc315d2 原生 TOML，并分离 managed state、revision、备份与回滚 | API 或 lifecycle 直接拼 TOML |
| CredentialBackend | Windows Credential Manager 固定引用、metadata/revision 与受限 Operation resolve；InMemory 仅测试 | 通用 Vault、明文回退、读取用户旧 Secret |
| Telegram Identity/Binding/Lease | getMe、Webhook、一次性绑定、offset 和 getUpdates 单一 Owner | 业务消息发送、完整 Bot Framework |
| ManagedProcessService | 所有权计划、start/stop/restart/status/reconcile、身份验证、日志与恢复 | 外部 supervisor 或通用服务管理器 |
| ProcessIdentityInspector | PID 创建时间、路径、SHA256、命令摘要和父 PID 证明 | 仅按进程名或 PID 猜测 |
| PortOwnershipInspector | loopback TCP 端口到 PID 映射、冲突和释放证明 | 抢占端口或终止占用者 |
| ArtifactProvider/UpdateSource | 当前/候选版本、精确策略、兼容性、迁移和回滚评估 | 本切片不执行自动更新 |
| ExternalToolProvider | CC Switch 能力声明、公开入口检测与普通打开 | 不读私有库、不读 Secret、不做 GUI 自动化 |

## 配置事务

旧兼容配置仍位于 `components/cc-connect/state/config/cc-connect.managed.toml`。合法运行使用两个独立事实源：`state/managed/cc-connect-state.json` 保存 product instance、Owner、revision、CredentialRef、Bot/binding 与证据引用；`state/runtime-config/cc-connect.toml` 只保存上游支持的 data_dir、management、Project、Agent、Telegram Platform、allow_from/admin_from 与 Secret 环境变量占位符。

写入流程为：生成计划快照与摘要，绑定 plan ID/digest/current revision/target revision/Idempotency-Key 显式确认，再次校验 current 指针、artifact、端口与现有 revision，保存备份，在同目录临时文件写入 UTF-8，flush/fsync 后使用 os.replace，重新解析与 schema 校验，最后提交 revision。失败时回滚；回滚失败持久化 pending_repair。

## 所有权与生命周期

ManagementOwner 与 LifecycleOwner 独立建模。安装不自动获取生命周期，配置写入不停止 external 进程。Owner 交接使用独立不可变计划和显式确认，只在结果为 product/product 时允许 start。

启动前校验 current/manifest/SQLite 一致性、artifact SHA256、native configuration revision、Owner、三 Bot 身份、Webhook、Update Lease、Claude/Codex 可执行入口、CredentialRef 和端口。Secret 从 Windows Credential Manager 临时解析，只注入目标子进程；argv 与 TOML 不含值。环境白名单保留 PATH 等必要非敏感系统变量，避免锁定版 cc-connect 无法发现已安装 Agent，但不修改系统 PATH。停止前完整匹配持久化身份并释放 runtime Lease。

## 身份、端口与健康

进程身份绑定 component ID、product instance ID、artifact ID、exe 规范绝对路径/SHA256、PID/创建时间、父 PID、启动命令摘要、configuration revision、listen host/port、LifecycleOwner 和 operation ID。PID 相同但创建时间不同视为复用；路径、SHA256、命令或端口 PID 不匹配均 fail closed。

健康证据分层保存 process identity、artifact integrity、configuration revision、port ownership、startup stability、management API 和 deep health。实测 management API 正确 Bearer 返回 200、错误 Bearer 返回 401；由于锁定上游没有 bind host 字段，监听范围是所有网卡，健康只能为 partial。deep health 仍 unsupported，进程或日志存在不会被等同为 complete healthy。

## 恢复与持久化

Control Plane 启动时先恢复 Operation：已终态操作不重复，未完成操作先用类型专属探针观测现场，再决定完成、失败或重入队列。生命周期 reconcile 用持久化身份重新验证进程与端口；无身份且期望 running 时保留 crashed，不虚报 stopped/running。

Alembic 0003 保留 Operation、旧配置和生命周期表；0004 新增 credential reference/revision、Telegram bot identity、binding session/slot/group/audit、update lease/offset、native configuration plan/revision/backup、renderer、Hermes plan 与 runtime Secret injection audit。数据库不保存 Secret、绑定码明文、完整 Telegram Update 或消息正文。

## 更新与外部工具

cc-connect 当前版本由 artifact lock、manifest、current 指针和持久化状态唯一确定。更新评估要求精确候选版本、来源、兼容性、迁移计划和回滚点，不支持 latest。Hermes 未有可执行更新 Adapter，准确返回 unsupported。

CC Switch 只根据公开可执行入口返回安装状态并可普通打开。install/update/configuration/ownership_handoff 缺少稳定公开接口证据时标为 unknown，不读取私有配置或 Secret，不修改 CC Switch 源码。

## 契约与验证

OpenAPI v1 以向后兼容增量方式增加配置计划/状态、Owner 计划/状态、start/stop/restart/reconcile/health、process identity、port ownership、update assessment 和 CC Switch detect/launch。`managed-runtime.schema.json` 为对应 Draft 2020-12 模型。

自动化覆盖 Credential 错误与 Secret 不回显、Telegram API/Lease/绑定攻击矩阵、Renderer 正反 Schema、中文空格括号路径、配置竞态/漂移/备份/回滚、Agent 缺失、external 检测、生命周期 PID/SHA/revision/端口/Owner、management Bearer 和 Control Plane 重启。真实 Telegram、Windows 10、Group Chat 原生过滤和 deep health 不得标为 COMPLETE。

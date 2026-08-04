# 12 cc-connect 受管运行与可升级边界

## 状态

实施日期：2026-08-04。自动化与隔离 Windows 11 证据已获得；锁定版 cc-connect 无 Secret 持续运行为 PARTIAL；Windows 10 x64 为 pending user real-machine validation。

## 范围与非目标

本切片只管理 Control Plane 自己安装的 cc-connect。它不修改 Reference Baseline、现有外部配置、计划任务、Watchdog、PATH、注册表或 Windows Service，不停止外部进程，不读写真实 Secret，不发送 Telegram 消息。

## 模块设计

| 模块 | 职责 | 不承担 |
|---|---|---|
| OperationExecutor | 有界队列、组件互斥、持久化 Operation、幂等、取消、关机和恢复探测 | 分布式任务、通用工作流 |
| ConfigurationService/ConfigStore | 不可变计划、revision、备份、原子替换、漂移检测与回滚 | 任意路径或外部配置编辑 |
| CredentialBackend | SecretRef 状态边界与可注入测试后端 | 本切片不读写真实凭据 |
| ManagedProcessService | 所有权计划、start/stop/restart/status/reconcile、身份验证、日志与恢复 | 外部 supervisor 或通用服务管理器 |
| ProcessIdentityInspector | PID 创建时间、路径、SHA256、命令摘要和父 PID 证明 | 仅按进程名或 PID 猜测 |
| PortOwnershipInspector | loopback TCP 端口到 PID 映射、冲突和释放证明 | 抢占端口或终止占用者 |
| ArtifactProvider/UpdateSource | 当前/候选版本、精确策略、兼容性、迁移和回滚评估 | 本切片不执行自动更新 |
| ExternalToolProvider | CC Switch 能力声明、公开入口检测与普通打开 | 不读私有库、不读 Secret、不做 GUI 自动化 |

## 配置事务

唯一可写目标是产品目录下的 `components/cc-connect/state/config/cc-connect.managed.toml`。schema 限定组件、artifact、product instance、127.0.0.1、受控端口段、产品自有数据/日志/项目目录、两类 Owner、revision、SecretRef、Telegram disabled、network mode 和 health probe 声明。

写入流程为：生成计划快照与摘要，绑定 plan ID/digest/current revision/target revision/Idempotency-Key 显式确认，再次校验 current 指针、artifact、端口与现有 revision，保存备份，在同目录临时文件写入 UTF-8，flush/fsync 后使用 os.replace，重新解析与 schema 校验，最后提交 revision。失败时回滚；回滚失败持久化 pending_repair。

## 所有权与生命周期

ManagementOwner 与 LifecycleOwner 独立建模。安装不自动获取生命周期，配置写入不停止 external 进程。Owner 交接使用独立不可变计划和显式确认，只在结果为 product/product 时允许 start。

启动前校验 current/manifest/SQLite 一致性、artifact SHA256、配置 revision、Owner、SecretRef 状态和端口可用性。进程使用参数数组、shell=False、固定 cwd、最小环境白名单、Windows 无窗口和新进程组。停止前必须完整匹配持久化身份，先优雅停止，再按已验证进程树 terminate/kill，最后证明端口释放。Windows Job Object 是未来可选加固，当前未声称已使用。

## 身份、端口与健康

进程身份绑定 component ID、product instance ID、artifact ID、exe 规范绝对路径/SHA256、PID/创建时间、父 PID、启动命令摘要、configuration revision、listen host/port、LifecycleOwner 和 operation ID。PID 相同但创建时间不同视为复用；路径、SHA256、命令或端口 PID 不匹配均 fail closed。

健康证据分层保存 process identity、artifact integrity、configuration revision、port ownership、startup stability、local endpoint 和 deep health。上游没有稳定无副作用本地 health endpoint，所以 local endpoint/deep health 是 unsupported；进程或日志存在不会被等同为 complete healthy。

## 恢复与持久化

Control Plane 启动时先恢复 Operation：已终态操作不重复，未完成操作先用类型专属探针观测现场，再决定完成、失败或重入队列。生命周期 reconcile 用持久化身份重新验证进程与端口；无身份且期望 running 时保留 crashed，不虚报 stopped/running。

Alembic 0003 增加 Operation job、configuration plan/revision/backup、pending repair、ownership plan、managed process、process identity、port ownership、lifecycle lease/event、external tool capability 和 update assessment 表。迁移支持空库、0002 升级、重复执行和回退到 0002。

## 更新与外部工具

cc-connect 当前版本由 artifact lock、manifest、current 指针和持久化状态唯一确定。更新评估要求精确候选版本、来源、兼容性、迁移计划和回滚点，不支持 latest。Hermes 未有可执行更新 Adapter，准确返回 unsupported。

CC Switch 只根据公开可执行入口返回安装状态并可普通打开。install/update/configuration/ownership_handoff 缺少稳定公开接口证据时标为 unknown，不读取私有配置或 Secret，不修改 CC Switch 源码。

## 契约与验证

OpenAPI v1 以向后兼容增量方式增加配置计划/状态、Owner 计划/状态、start/stop/restart/reconcile/health、process identity、port ownership、update assessment 和 CC Switch detect/launch。`managed-runtime.schema.json` 为对应 Draft 2020-12 模型。

自动化覆盖配置竞态、过期、digest、漂移、占用、回滚、路径逃逸；Operation 队列、互斥、幂等、取消、关机和恢复；生命周期重复操作、超时、强制终止、PID 复用、SHA/revision/端口/Owner 冲突、崩溃与 Control Plane 重启；以及更新与 ExternalToolProvider 不虚报能力。

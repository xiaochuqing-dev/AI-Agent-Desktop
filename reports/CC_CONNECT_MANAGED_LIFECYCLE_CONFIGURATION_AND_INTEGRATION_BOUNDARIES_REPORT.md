# cc-connect 产品管理生命周期、最小配置与可升级集成边界报告

## 1. Executive Summary

本阶段完成了 OperationExecutor、cc-connect 最小非敏感配置、revision/备份/回滚、SecretRef/CredentialBackend 边界、显式所有权交接、产品自有进程启停重启、PID 复用与端口所有权验证、Control Plane 重启恢复，以及 cc-connect/Hermes/CC Switch 可升级边界。自动化和 Windows 隔离机制通过；锁定版 cc-connect 要求至少一个 Project 和 Platform，本阶段的 Telegram-disabled、无 Secret 配置无法满足运行前提，故真实持续运行结论为 PARTIAL，不虚报 COMPLETE。

## 2. 实际开始时间

2026-08-04T14:23:48+08:00（Asia/Shanghai）。

## 3. 开始时 main SHA

28a29cc73e6364585203abf56103ec74d088482d，提交为 `docs(report): complete cc-connect Windows installation slice`。开始时本地 main 与 origin/main 一致，工作区 clean。

## 4. 产品方向未改变声明

产品仍是面向 Windows 10/11 开发者的 Telegram AI 编程团队安装、配置、管理、诊断与恢复中心。Agent 仍为 Hermes、Claude Code、Codex；cc-connect 仍为 V1 核心桥梁；CC Switch 仍是推荐但非强制外部入口。未新增 Agent、Channel、GUI 或通用平台。

## 5. 本阶段准确范围

只管理 Control Plane 自己安装的锁定 cc-connect Windows amd64 版本，完成非 Secret 配置、明确所有权、本地进程/端口/有限健康证据、恢复与回滚。不连接真实 Telegram，不写真实 Token/API Key/ID，不安装 Hermes/Claude Code/Codex。

## 6. 结构债拆分结果

未重写 Control Plane。新职责分到 `operations/`、`configuration/`、`lifecycle/`、`updates/`、`external_tools/` 和 `api/routers/`；安装器只新增 `version_store.py` 隔离已安装版本验证，未把配置或生命周期继续塞入 CcConnectInstaller。

## 7. OperationExecutor

实现单进程、有界队列、非 daemon worker、持久化 job、每组件互斥、幂等提交、安全取消点、关机等待/超时、审计和可注入 handler/probe。重启时终态不重复，未完成操作先探测现场再决定完成、失败或重入队列。不引入 Celery、Redis、RabbitMQ 或分布式执行器。

## 8. 最小配置 Schema

唯一产品写入路径是 `components/cc-connect/state/config/cc-connect.managed.toml`。严格 schema 仅允许 schema/component/artifact/product instance、127.0.0.1、59000–59999 端口、产品自有目录、Owner、revision/时间、SecretRef、Telegram disabled、network mode 和 health probe 声明。未知字段、任意路径、0.0.0.0 和明文凭据被拒绝。

## 9. 配置计划与确认

计划持久化 plan ID/digest/context digest、artifact/current/target revision、Owner、目标路径、变更、端口、目录、SecretRef、风险、回滚和过期时间。确认必须绑定 plan ID/digest/current/target revision、`confirmation=true` 和 Idempotency-Key。current、artifact、revision、端口或计划上下文变化即失效。

## 10. 配置 revision

配置从 revision 1 单调增长。每次写入前检查当前 revision 和内容摘要；并发旧计划返回 `CONFIGURATION_REVISION_CONFLICT`。回滚不修改历史，而是以旧内容新建一个 revision。

## 11. 原子写入

同目录临时文件使用 UTF-8 写入，flush/fsync 后调用 os.replace。替换后重新解析并做 schema、路径、权限和摘要校验。不使用先删旧文件、shell 拼路径或跨卷搬运。

## 12. 备份与回滚

替换前建立可校验备份并持久化元数据。写入、解析、schema 或元数据提交失败都尝试恢复原文件。回滚也是显式 Operation；恢复失败生成 pending_repair 和稳定 Diagnostic，不虚报成功。

## 13. SecretRef 边界

SecretRef 只含不透明 ref ID、purpose 和存在性需求，不包含解析值。状态只能是 missing/available/inaccessible/unknown。配置、SQLite、Operation、日志、事件和 Diagnostic 都不保存 Secret 值。

## 14. CredentialBackend 状态

CredentialBackend 接口和 Fake/InMemory 状态后端已实现并可注入测试。Windows Credential Manager 适配器骨架已存在，但本阶段不读写真实凭据，准确返回 unknown。真实 Secret 写入为 UNSUPPORTED/DEFERRED。

## 15. start/stop/restart

start/stop/restart/status/reconcile 均已实现为持久化 Operation。start 执行 current/manifest/DB/SHA/config/Owner/SecretRef/端口预检，用参数数组、shell=False、固定 cwd、环境白名单、无窗口和新进程组启动。stop 先优雅停止，超时后只对已验证树 terminate/kill并证明端口释放。restart 串行停止、重验证、启动，中间失败不虚报 running。

## 16. 进程身份

身份绑定 component ID、product instance ID、artifact ID、exe 规范绝对路径/SHA256、PID、创建时间、父 PID、命令摘要、configuration revision、listen host/port、LifecycleOwner 和 operation ID。不依赖进程名或单独 PID 文件。

## 17. PID 复用防护

PID 存在但创建时间不匹配返回 `MANAGED_PROCESS_PID_REUSED`。路径、SHA256 或命令摘要不匹配分类为 identity/integrity failure。stop/restart 在任一身份证据不匹配时 fail closed，不向该 PID 发信号。

## 18. 端口所有权

仅允许 127.0.0.1 和受控端口段。计划、写配置、启动前和启动后都检查端口；运行后必须证明 LISTEN 属于目标 PID。外部占用返回 `MANAGED_PORT_CONFLICT` 或 `MANAGED_PORT_OWNED_BY_OTHER_PID`，不杀占用进程。IPv6 未证明能力为 unknown/unsupported。

## 19. LifecycleOwner

LifecycleOwner 枚举 external/product/none/conflict/unknown。安装不自动获取生命周期所有权；只有 product 允许 start/stop/restart。external/conflict/unknown 都阻断变更。

## 20. ManagementOwner

ManagementOwner 枚举 external/product/unmanaged/conflict/unknown。受管配置仅在 product 范围写入，不读写 CC Switch、Hermes、官方 Agent 或 Reference Baseline 配置。

## 21. external 冲突处理

所有权交接是独立不可变计划，需用户显式确认。发现外部进程、外部 Owner 或冲突 Owner 时返回稳定 Diagnostic，不关闭、不接管、不修改外部启动定义。隔离验收得到 `EXTERNAL_LIFECYCLE_CONFLICT`。

## 22. 本地健康证据

健康模型独立记录 process identity、artifact integrity、configuration revision、port owned by process、startup stability、local endpoint 和 deep health。没有全部直接证据时不会聚合为 complete healthy。

## 23. deep health 限制

锁定上游无稳定、无副作用的本地 health endpoint。local endpoint 与 deep health 标记 unsupported；进程、端口或日志存在都不能替代 deep health。未为此增加 cc-connect Patch。

## 24. Control Plane 重启恢复

启动时 OperationExecutor 恢复未终态 job，ManagedProcessService 按持久化身份 reconcile。已崩溃且期望 running 的实例在无 PID 后仍保留 crashed，不误报 stopped。真实隔离验收重启观测为 crashed，与上游无 Secret 退出事实一致。

## 25. Windows 路径兼容

单元测试和真实隔离验收使用中文、空格、括号路径，且实验产品目录位于非系统盘。启动与文件操作均不使用 shell 字符串拼接。

## 26. 普通用户权限

隔离安装与受管运行验收观测 `is_admin=false` 和 `ordinary_user_observed=true`。不默认提权，不创建系统服务或全局安装。

## 27. PowerShell 5.1/7

PowerShell 5.1 用户验收包装骨架在本机通过语法/运行检查。本机未安装 PowerShell 7；Windows Server 2022 CI Run 30890477563 同时用 Windows PowerShell 5.1 和 PowerShell 7 校验 Patch、双构建、产物与验收入口，全部 success。

## 28. Windows 10 状态

PENDING USER VALIDATION。当前没有 Windows 10 x64 实机证据，脚本存在不等于已验证。

## 29. Windows 10 用户验收准备

`control-plane/scripts/windows10_user_acceptance.ps1` 已准备为无开发环境依赖的未来打包入口骨架，可输出脱敏 JSON。它会在非 Windows 10 x64 主机准确返回 `NOT_WINDOWS_10_X64`，且只有未来打包 runner 完整成功才能标记 validated。

## 30. cc-connect 更新边界

ComponentDescriptor、InstalledVersion、AvailableVersion、UpdateChannel、UpdateSource、VersionPolicy、CompatibilityRule、ArtifactProvider、UpdateAssessment 和 MigrationPlan 已建模。当前版本只从 artifact lock/manifest/current/DB 获取，不散落硬编码、不使用 latest。本阶段只评估，不下载或升级。

## 31. Hermes 更新边界

Hermes 可在未来通过独立 ArtifactProvider/UpdateSource 提供版本、来源、兼容性、配置 schema、Profile/Gateway、回滚点和所有权评估。当前未实现来源或执行器，准确返回 unsupported；没有安装或升级 Hermes。

## 32. CC Switch ExternalToolProvider 边界

ExternalToolDescriptor 持久化 installed/version/executable/source、supported agents、install/update/configuration/ownership_handoff 能力、status、verified_at 和 evidence。只有公开可执行文件检测与普通打开为 supported/read_only；安装、更新、配置和所有权交接在无稳定证据时为 unknown。

## 33. CC Switch 未修改源码证明

没有 clone、fork、patch 或修改 CC Switch 源码，没有复制其安装实现。Adapter 不读其私有数据库或配置目录，不读 Secret，不注入进程，不自动点击 GUI。

## 34. Hermes Studio 非目标

本阶段未拉取、嵌入、修改或实现 Hermes Studio Adapter。Hermes Studio 仍是未来可选外部工作区，不是 V1 核心依赖。

## 35. 选择性 GitHub 调研内容

查验了 Microsoft Job Objects、GetProcessTimes/Process Information、GetExtendedTcpTable、Process Creation Flags、MoveFileEx/ReplaceFile、Windows Credential Manager；Python os.replace/subprocess 和 psutil 文档；cc-connect 锁定 commit 的 CLI/运行前提；CC Switch 官方仓库与公开深链边界。资料与取舍已记录在 `architecture/control-plane-v1/11_OPEN_SOURCE_DESIGN_REFERENCES.md`。

## 36. 新增依赖及理由

无新增运行或开发依赖。现有 psutil、keyring、SQLAlchemy、FastAPI、Pydantic 与标准库足以完成切片。

## 37. 未引入依赖的关键决策

未引入 Job Object 封装、Windows Service wrapper、新凭据库、消息总线、队列服务、通用插件系统或更新框架。当前 psutil 进程树与端口映射已可验证；Job Object 保留为未来加固选项，不虚报已实现。

## 38. API/契约变更

OpenAPI v1 向后兼容增加 configuration plan/get/apply/state、ownership plan/get/confirm、start/stop/restart/reconcile/health、lifecycle status、process identity、port ownership、owners、cc-connect/Hermes update assessment 和 CC Switch detect/launch。新增 `managed-runtime.schema.json`，并纳入契约校验和正反样例测试。原安装端点不变。

## 39. Alembic migration

0003 新增 operation_jobs、configuration_plans/revisions/backups、pending_repairs、ownership_plans、managed_processes、process_identity_records、port_ownership_records、lifecycle_leases/events、external_tool_capabilities 和 update_assessments。已测试空库、旧库、0002→0003、重复 upgrade、0003→0002 downgrade 后再 upgrade，不保存 Secret 明文。

## 40. 修改文件清单

核心新增集中在 `control-plane/control_plane/operations/`、`configuration/`、`lifecycle/`、`updates/`、`external_tools/`、`api/routers/`、`installer/version_store.py` 和 Alembic 0003。契约新增 managed-runtime schema 并扩展 OpenAPI。测试新增 operation/configuration/lifecycle/process-port/update-external 五组文件与 Windows 验收脚本。事实源更新根目录、product、architecture、integrations、control-plane、next-agent 和本报告。最终精确列表由本阶段 Git commit 与 `PUBLIC_FILE_MANIFEST.txt` 提供。

## 41. 本地测试命令

```text
cd control-plane
python -m ruff format .
python -m ruff check .
python -m mypy control_plane
python scripts/validate_contracts.py
python -m pytest -q
python scripts/windows_isolated_acceptance.py --artifact-bundle <locked-bundle> --output <sanitized-json>
python scripts/windows_managed_runtime_acceptance.py --artifact-bundle <locked-bundle> --output <sanitized-json>
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/windows10_user_acceptance.ps1 -OutputPath <sanitized-json>
```

## 42. 自动化测试结果

Ruff format/check、mypy 和四份契约验证通过；pytest 133 passed、1 skipped。1 个既有 Starlette/httpx 弃用警告。最终全量复验用时 15.99 秒。

## 43. Windows CI Run ID

GitHub Actions Run ID 30890477563，head SHA `ae69444c361ac75b049a8ef61534a5f768b34494`，结论 success。三个 job 均通过：Platform-independent core compatibility、Windows-first quality gates、Locked cc-connect Windows artifact and isolated acceptance。最后一个 job 包括精确上游 commit、5 个 Patch、Go 测试、双构建一致性、PowerShell 5.1/7、两套真实 Windows 验收、Windows 10 包装入口和 Artifact 上传。证据 URL：https://github.com/xiaochuqing-dev/AI-Agent-Desktop/actions/runs/30890477563。

## 44. 真实 Windows 隔离验收

Windows 11 x64（Python API 报告 build 26100，PowerShell 系统查询报告 build 26200）、普通用户、非系统盘、中文/空格/括号路径上，锁定产物 SHA256 `cd1b0787709c0401a42f7c3ce5321184889adbfbf3b080190fee180afc977eec` 的安装验收 PASSED。受管运行验收 PARTIAL：配置 revision 1→3、竞态、回滚到 revision 1、Owner、端口/外部冲突、停止和重启恢复证据正确；真实 start 因上游运行前提不满足而得到 `MANAGED_PROCESS_EXITED_DURING_STARTUP`，restart 也准确失败。结束后无受管残留进程。同样的两套验收在 Windows Server 2022 CI Run 30890477563 中通过脚本预期判定。

## 45. 失败场景矩阵

| 场景 | 稳定结果 |
|---|---|
| 计划过期/digest 不匹配 | CONFIGURATION_PLAN_EXPIRED / CONFIGURATION_CONFIRMATION_MISMATCH |
| revision 竞态/手工修改 | CONFIGURATION_REVISION_CONFLICT / CONFIGURATION_MANUAL_DRIFT |
| 文件占用/写后校验/回滚失败 | CONFIGURATION_FILE_LOCKED / CONFIGURATION_POST_WRITE_VALIDATION_FAILED / CONFIGURATION_ROLLBACK_FAILED + pending_repair |
| symlink/junction 逃逸 | INSTALL_PATH_UNSAFE 或 CONFIGURATION_PATH_UNSAFE |
| 启动超时/无 Secret 退出 | MANAGED_PROCESS_STARTUP_TIMEOUT / MANAGED_PROCESS_EXITED_DURING_STARTUP |
| PID 复用/exe SHA 不匹配 | MANAGED_PROCESS_PID_REUSED / MANAGED_PROCESS_EXECUTABLE_INTEGRITY_FAILURE |
| 端口占用/属于其他 PID | MANAGED_PORT_CONFLICT / MANAGED_PORT_OWNED_BY_OTHER_PID |
| external/conflict Owner | LIFECYCLE_OWNER_NOT_PRODUCT 或 EXTERNAL_LIFECYCLE_CONFLICT，无外部副作用 |
| 崩溃/Control Plane 重启 | observed_state=crashed，不虚报 running/stopped |
| 更新源或 CC Switch 能力无证据 | unsupported/unknown，automatic_update_performed=false |

## 46. Reference Baseline 未修改证明

本阶段未修改 `reference-baseline/`、`src/` 或 `integrations/cc-connect/patches/`。真实隔离验收输出 `reference_baseline_modified=false` 且 `external_candidate_unchanged=true`。最终提交前再以 Git path diff 复核。

## 47. 计划任务/Watchdog/PATH 未修改证明

真实验收输出 `scheduled_task_modified=false`、`watchdog_modified=false`、`path_unchanged=true`、`registry_modified=false`、`windows_service_created=false`。实现不包含 schtasks、Service 注册、PATH 写入或 Watchdog 编辑逻辑。

## 48. 未发送真实 Telegram 消息证明

两份真实 Windows 隔离验收均输出 `telegram_messages_sent=0`。健康检查不连接 Telegram，本阶段未执行 getMe、绑定或六链路 E2E。

## 49. 未写入真实 Secret 证明

隔离验收输出 `real_secret_values_read=0`、`real_secret_values_written=0`、`synthetic_secret_leaks=[]`。环境白名单测试确认 Telegram/OpenAI/proxy 敏感变量不传入子进程。代码、配置、SQLite、日志、事件和 API 只保存 SecretRef 或脱敏状态。

## 50. 未解决问题

PARTIAL：锁定版 cc-connect 要求 Project+Platform，无 Secret/Telegram-disabled 合成配置无法满足运行前提。UNSUPPORTED：稳定 local endpoint/deep health、真实 Windows Credential Manager 读写、Hermes/cc-connect 自动更新、CC Switch 安装/更新/配置。PENDING USER VALIDATION：Windows 10 x64 实机。DEFERRED：Telegram 三 Bot 绑定、User/Group ID 发现、六链路 E2E、正式 GUI、代码签名、Job Object 加固和 IPv6 所有权证明。cc-connect 产物仍为 unsigned。

## 51. 下一阶段准确任务

Telegram 三 Bot 安全绑定、自动身份发现与配置生成切片。先完成不回显明文的 Windows CredentialBackend 和锁定版持续运行门禁，再在用户显式启动下实现三 Token 安全录入、getMe、一次性绑定码、User/Group ID 发现、三 Bot 同群一致性与 Hermes/cc-connect 可回滚配置。不直接跳到 GUI。

## 52. 最终 main SHA

最终精确 SHA 由交付完成后的 origin/main 提供，并在最终用户回执中记录。Git 提交无法在自身已提交内容中无循环地嵌入自己的 SHA；本报告不写伪值。阶段实现与完整 Windows CI 基准 SHA：`ae69444c361ac75b049a8ef61534a5f768b34494`。

## 53. 最终分支列表

实现提交推送后已复核：本地仅 main，远端仅 `refs/heads/main`。本阶段未创建分支或 PR；最终证据提交后再次复核。

## 54. 最终 git status

实现提交与 Run 30890477563 完成后曾复核 main 与 origin/main 一致、working tree clean。回填本报告的最终证据提交推送后再次复核，精确结果同时在用户回执记录。

## 55. 回滚本阶段代码的方法

在 main 上使用 `git revert` 按逆序回退本阶段语义提交，正常推送并等待同一 CI；不得 reset、force push 或改写历史。本阶段未修改 Reference Baseline、外部进程、真实配置、计划任务、Watchdog、PATH 或注册表，因此代码回滚不需恢复这些外部状态。

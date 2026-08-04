# cc-connect Windows 可分发产物与隔离真实安装闭环报告

## 1. Executive Summary

状态：COMPLETE（以本报告记录的最终 GitHub Actions 全绿为准）。本阶段完成锁定 cc-connect Windows amd64 产物、机器 Manifest、可重复构建、显式计划确认、当前用户隔离安装、持久化审计、离线验证、自动回滚、卸载与恢复闭环。

## 2. 实际开始时间

2026-08-04T11:49:52+08:00。该时间为首个隔离构建根目录的可验证创建时间；Git/GitHub 起点审计在其前立即完成。

## 3. 开始时 main SHA

53a9fd8be511818d195f9a7f07e8f758745c101a。开始时本地 main 与 origin/main 一致，工作区 clean，本地和远端都只有 main。

## 4. 产品方向未改变声明

仍为 Windows 10/11 + Telegram + Hermes、Claude Code、Codex；cc-connect 仍是 V1 核心桥梁；CC Switch 仍为推荐但非强制入口。未新增 Agent、Channel 或通用平台能力。

## 5. 本阶段准确范围

只实现 cc-connect Windows 可分发产物与产品自有隔离安装闭环。未实现 Telegram 自动绑定、六链路 E2E、正式 GUI、其他组件安装、Provider 编辑器或配置写入。

## 6. Windows 支持范围

supported：Windows 10 x64、Windows 11 x64，当前用户权限安装。

## 7. 不支持的 Windows 架构

unsupported：windows/386、windows/arm64。

## 8. cc-connect 锁定基线

上游版本 1.4.1，产品版本 v1.4.1-patchset0.1-fc315d2，Artifact ID 为 cc-connect-v1.4.1-patchset0.1-fc315d2-windows-amd64。

## 9. 上游 Commit

仓库 https://github.com/chenhg5/cc-connect.git，Commit fc315d213b49d62e9d90ea4a510189d4115e636f。未升级上游。

## 10. Patchset 与 Patch 摘要

Patchset 0.1，共 5 个，按 001 至 005 固定顺序。SHA256 分别为 475441717ea8ddafa216a0440e66eaaac2cf2e04001b4469e4cca91e75069745、a59c42b63dfcf9662188831c6a57695ecfa03491d2041f111dbe4f5c256f6cae、3a7cdc0af7ac156b72598b39e47fda2c2b4e071dbf769c0ee83cd30f7b7b3ce8、dc4a5a9c4830ddf46778c5e192840e1c8f5a89b59994dc968aea024b0a907ddf、a23f557bc2ce36469f6d55e1a0dc019fb3cb31056d03a5e524ff57ae12494fd0。

## 11. Go 版本

Go 1.26.5，GOOS=windows，GOARCH=amd64，CGO_ENABLED=0，GOTOOLCHAIN=local。安装侧不要求 Go、Node 或 npm。

## 12. Build tags 和 ldflags

Tags：no_web、goolm、no_pi。ldflags：-buildid= -s -w -X main.version=v1.4.1-patchset0.1-fc315d2 -X main.commit=fc315d2 -X main.buildTime=2026-07-19T12:15:03Z。

## 13. 可重复构建策略

锁定源码、Patch 与 Patch 后文件摘要、Go、tags、ldflags、SOURCE_DATE_EPOCH=1784463303，并关闭 buildvcs、启用 trimpath。四个本地构建（含 PowerShell 5.1 与 7.6.4）得到相同 SHA256；CI 再由两个 PowerShell 版本各构建一次并比较。

## 14. Artifact Manifest

构建生成 cc-connect-artifact-manifest.json 和 cc-connect.sha256。Manifest 包含来源、Commit、Patch、工具链、构建输入、大小、摘要、兼容性、签名状态、布局版本和健康探针版本，不含用户名、绝对路径或 Secret。

## 15. Artifact SHA256

cd1b0787709c0401a42f7c3ce5321184889adbfbf3b080190fee180afc977eec；大小 26928640 字节；PE Machine 0x8664。

## 16. 签名状态

signature_status=unsigned。未绕过 SmartScreen、未关闭 Defender、未添加白名单。

## 17. GitHub Actions Artifact/Release 信息

Actions Artifact 名称：cc-connect-v1.4.1-patchset0.1-fc315d2-windows-amd64；Run ID：30880682335；Artifact ID：8881245305；上传包 digest 为 sha256:f26647acc4a039bcdbd6ccee9ad84f79bf960ef5d09ddd22f8cda115264195b5；保留 30 天。下载复核后的 exe SHA256 仍为 cd1b0787…。未创建 Release，也未发布 npm。

## 18. 安装目录布局

platformdirs LocalAppData/AI-Agent-Desktop/components/cc-connect 下使用 current.json、versions/<artifact-id>、staging/<operation-id>、backups/<operation-id> 和 state/pending-cleanup.json。每个版本独立。

## 19. 权限模型

requires_admin=false。真实验收进程 IsUserAnAdmin=false；未写 Program Files、System32、系统注册表、系统 PATH 或 Windows Service。

## 20. Windows 路径兼容验证

真实验收使用 D 盘临时根、中文、空格、括号和 225 字符的产品管理产物路径。未要求修改 LongPathsEnabled；超过传统 MAX_PATH 的路径不虚报支持。

## 21. PowerShell 5.1/7 验证

Windows PowerShell 5.1 已在本机验证 Patch、构建和产物校验；官方便携 PowerShell 7.6.4 也在本机完成构建与校验，并得到相同 SHA256。PowerShell 7 会把 JSON ISO 时间自动解析为 DateTime，脚本已用 UTC invariant 格式规范化；固定 windows-2022 CI 再验证 runner 自带 pwsh。

## 22. 下载与代理处理

仅允许锁定 HTTPS 主机，逐次校验重定向，保留 TLS 校验，支持系统与 HTTP_PROXY/HTTPS_PROXY、超时、重试、Range 续传、.part、最大大小和取消。URL 凭据、query token、未知主机、TLS 与代理认证失败均返回稳定 Diagnostic。

## 23. Operation 状态机

阶段覆盖 planned、waiting_for_confirmation、preflight、snapshotting、acquiring、verifying、installing_to_staging、validating、activating、completed，以及 cancelling/cancelled、rolling_back/rolled_back、rollback_failed、failed、pending_cleanup。v1 顶层状态保持向后兼容，细阶段写入 progress.phase。

## 24. Idempotency

Idempotency-Key 与方法、资源、请求摘要、Operation 持久绑定；同 key 同请求返回原 Operation，不同请求冲突。同 Artifact 已安装返回 no-op；组件级持久租约阻止并发执行者。

## 25. 取消语义

下载、验证和 staging 安全检查点可取消；只有实际停止后才标 cancelled。激活 point of no return 后的取消请求被审计但不虚报立即停止，Operation 继续完成或真实回滚。

## 26. Point of No Return

current.json 原子切换前进入 activating 并设置 point_of_no_return=true；切换前重新校验计划、产物、目标目录和 current revision。

## 27. 安装前快照

记录当前产品版本、current 指针、目录摘要、ManagementOwner、生命周期所有者、发现状态、配置引用位置、产品进程状态、磁盘空间和目标目录状态，不读取 Secret。

## 28. 激活方式

同卷 staging 完成后转入不可变 version 目录；current.json 通过临时文件、flush/fsync 和 os.replace 原子切换。不覆盖运行中的全局 cc-connect.exe，不依赖 symlink。

## 29. 回滚方式

失败恢复原 current、Owner、生命周期所有者、安装记录和产品管理状态，并校验旧目标存在和摘要。回滚失败标 rollback_failed，保留快照和人工恢复 Diagnostic。

## 30. 卸载与恢复

可卸载已登记的非当前产品管理版本；当前版本拒绝删除。restore 切回已登记、摘要匹配的 previous_artifact_id。Windows 文件占用进入 pending_cleanup，释放后可重试。

## 31. ManagementOwner 处理

允许 external、product、unmanaged、conflict、unknown。发现 external 时隔离安装可继续，但结果保持 external，lifecycle_takeover=false，不启动实例、不写配置、不抢端口。

## 32. 隔离健康验证

验证文件、大小、SHA256、PE amd64 和 --version。探针使用临时工作目录、合成配置、随机 loopback 端口、清空环境、无代理、无窗口、10 秒超时和进程树清理。未访问 Telegram。上游完全离线深度启动不受支持，deep_health=unsupported，不伪造 healthy。

## 33. Alembic migration

新增 0001 基线和 0002 cc-connect installer 迁移；启动时 upgrade head。空库、旧 create_all Schema 升级和重复迁移幂等均通过；不再使用 create_all 作为正式升级路径。

## 34. API/契约变更

新增 install-plan 创建/读取、cc-connect install、uninstall、restore、managed-versions 和 Operation 持久事件表达；核心 Schema 新增 ArtifactManifest、InstallPlan、InstallSnapshot、ManagedVersion、OperationAuditEvent。其他组件调用返回 CAPABILITY_UNSUPPORTED。

## 35. 安全措施

保持 loopback、Bearer、Host 校验、query token 禁止和全链路脱敏。拒绝任意 URL、任意路径、重复 JSON key、Manifest 路径、路径穿越、symlink/junction 逃逸、超限文件和未校验执行；子进程不使用 shell=True。

## 36. 修改文件清单

主要变更位于 .github/workflows/control-plane-ci.yml、integrations/cc-connect 的锁文件与四个 PowerShell 脚本、control-plane 的 installer/persistence/api/security、Alembic、tests、Windows 验收脚本、contracts/control-plane-v1、architecture/control-plane-v1、根事实源文档、next-agent 提示词与本报告。src、reference-baseline 和 5 个 Patch 内容未修改。

## 37. 本地测试命令

执行 ruff check、ruff format --check、mypy control_plane、pytest -q、scripts/validate_contracts.py；执行 PowerShell 5.1 Patch/Build/Verify；执行相关 Go test；执行 windows_isolated_acceptance.py，并在 D 盘临时 LocalAppData 中使用真实产物。

## 38. 自动化测试结果

本地最终结果：91 passed、1 skipped（仅当前账号不可创建 symlink 时跳过）、ruff/format/mypy 全通过。契约校验全部通过；相关 Go core 与 telegram 测试通过；三个构建摘要一致；真实 Windows 隔离验收 status=passed。

## 39. Windows CI Run ID

30880682335，conclusion=success。Windows-first quality、Ubuntu 平台无关核心、锁定 Windows 产物与隔离验收三个 Job 全部成功。

## 40. Windows 隔离验收环境

本地验收为 Windows 11 x64，Python 记录 platform_version 10.0.26100，非管理员，D 盘临时根。CI 验收为 windows-2022 runner，platform_version 10.0.20348，runner 账户为管理员但安装计划仍为 requires_admin=false，同样使用非系统盘临时根。两者都由 platformdirs 覆盖到临时 LocalAppData，bundle SHA256 为 cd1b0787…；结束后临时目录、进程和文件占用均清理。

## 41. 失败场景结果

30 项均有自动化或真实验收证据：首次安装、重复安装、幂等重试、并发阻止、下载中断、TLS、代理、SHA、Manifest、架构、磁盘、staging 权限、文件占用、下载取消、验证取消、不可逆点取消、健康失败、激活前崩溃、current 写失败、回滚成功、回滚失败、重启恢复、pending_cleanup、卸载非当前、拒绝卸载当前、恢复上一版本、external Owner、中文空格路径、PowerShell 5.1、PowerShell 7。最终均为 PASS，PowerShell 7 证据来自 CI。

## 42. Reference Baseline 未修改证明

相对开始 SHA，src/、reference-baseline/、integrations/cc-connect/patches/ 无内容差异。验收前后外部 cc-connect 候选的路径、大小和 mtime 不变；未修改计划任务、Watchdog 或运行服务。

## 43. 未发送真实 Telegram 消息证明

验收仅执行 --version 探针，环境无真实 Token，NO_PROXY=* 且代理清空；telegram_messages_sent=0。没有运行六链路 E2E。

## 44. 未写入真实 Secret 证明

使用合成 canary Token 并扫描临时产品数据；synthetic_secret_leaks=[]。API、数据库、事件、Diagnostic、日志和 Manifest 不存明文 Secret。

## 45. 未解决问题

产物未代码签名，SmartScreen 分发体验仍受影响。上游没有完全离线深度健康模式，因此只支持 version-only 探针。生命周期接管、配置/凭据写入、自动更新、ARM64、GUI 和 Telegram 自动绑定均未实现。传统 MAX_PATH 以上路径未声明支持。

## 46. 下一阶段准确任务

cc-connect 产品管理生命周期与最小配置写入切片：产品自有实例 start/stop/restart、端口所有权、最小配置模板、SecretRef、无真实 Telegram 的本地运行闭环；仍不得跳到 GUI 或自动绑定。

## 47. 最终 main SHA

最终精确 SHA 由交付完成后的 origin/main 提供，并在最终用户回执中记录。Git 提交无法在自身已提交内容中无循环地嵌入自己的 SHA；本报告不写伪值。阶段实现基准 SHA：89ca107e0cadc945dcfb5a4cefb88b3fd895c25f。

## 48. 最终分支列表

最终验收结果：本地分支列表仅 main；`git ls-remote --heads origin` 仅 refs/heads/main。报告提交推送后再次复核。

## 49. 最终 git status

最终验收结果：报告提交推送并完成最终 CI 后，main 与 origin/main 一致，working tree clean；精确结果同时在用户回执记录。

## 50. 回滚本阶段代码的方法

在 main 上使用 git revert 按逆序回退本阶段语义提交，再推送并等待同一 CI；不得 reset、force push 或删除历史。Reference Baseline 与外部运行服务未被替换，因此代码回滚不需要恢复真实 Telegram 或计划任务状态。

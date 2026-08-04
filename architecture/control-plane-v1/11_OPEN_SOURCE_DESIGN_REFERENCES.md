# 11 开源成熟方案取舍

## 调研原则

本轮只借鉴经过实际使用的窄接口与协议习惯，不复制完整平台。检索快照日期为 2026-07-30，引用 commit 用于说明当时阅读的事实，不构成本产品依赖锁。

| 项目与快照 | 借鉴内容 | 在本设计中的落点 | 明确不采用 |
|---|---|---|---|
| [Podman Desktop](https://github.com/podman-desktop/podman-desktop/tree/d724411a9af61ec04d79af50657fa1deb1c3ea72) | Provider 的检测、安装、更新、生命周期、连接状态、取消 token 与事件 | Provider 描述符、LifecycleProvider、正交状态与用户提示 | Electron 技术栈、容器领域模型、扩展市场 |
| [HashiCorp go-plugin](https://github.com/hashicorp/go-plugin/tree/6c25fd9ffe730cb13403859c34ba814e9a25a67c) | 客户端与实现列出支持版本并选择最高兼容版本，失败时明确 incompatibility | `supported_contract_versions`、`negotiated_contract_version` 与主版本不兼容错误 | Go 绑定、进程外插件协议、magic cookie 作为安全边界 |
| [Kubernetes apimachinery](https://github.com/kubernetes/apimachinery/tree/eed236ceee2c19c2753a3d93ac0631dc20750454) | Condition 的 type/status/reason/message/observedGeneration/lastTransitionTime；resourceVersion 并发控制 | StateSnapshot、Condition、revision、`If-Match` 与陈旧观测识别 | Kubernetes API server、控制器循环、CRD 与集群语义 |
| [Google long-running operations](https://github.com/googleapis/googleapis/tree/b8486a2f44f15dc578a9dc1e17b144253079d5c1/google/longrunning) | 长操作资源、metadata、完成后 error/response 二选一、取消是尽力而为 | Operation、进度、轮询、取消请求和终态规则 | protobuf/gRPC 依赖、云资源命名体系 |
| [CloudEvents 1.0](https://github.com/cloudevents/spec/tree/c2845a49bc9831be02f305a4a792401b932d77d4) | `id/source/specversion/type/time/subject/data` 与重复事件识别 | 统一事件信封和 SSE data；增加 sequence/epoch/resourceversion 扩展 | 外部事件代理、消息总线、跨网络发布 |
| [Docker credential helpers](https://github.com/docker/docker-credential-helpers/tree/6bcdedb630ade6022bf70d3f9c1f0471785e7ee5) | Store/Get/Erase/List 与平台原生 keystore 分离 | CredentialProvider 的最小后端边界；GUI 只看元数据 | 服务器 URL 作为本产品凭据主键、把 Secret 返回给 GUI |
| [Dapr components-contrib SecretStore](https://github.com/dapr/components-contrib/tree/e6eb488ab5c4a7916c7a91a8e5b1ca0aed6a1670/secretstores) | SecretStore 初始化、取用、能力声明、健康探测 | CredentialProvider 的 feature 声明、validate/health 与可替换后端 | Dapr sidecar、分布式组件运行时、批量导出明文 |
| [Jupyter Server](https://github.com/jupyter-server/jupyter_server/tree/9a4d6eea2b16815a493b11fffe0b51b1fe55a81b) | 随机本地 token、Authorization header、Host/Origin 防护经验 | loopback API 高熵 token、Header 鉴权、精确 Origin 策略 | URL query token 兼容、浏览器登录 cookie、关闭鉴权 |

## 关键取舍

### Provider 模型不等于插件系统

Podman Desktop 与 go-plugin 证明了能力声明、生命周期和版本协商的价值，但本产品 v1 只为内置 Adapter 定义端口。引入任意第三方插件会扩大供应链、权限和崩溃隔离问题，不是第一个纵向切片所需。

### Operation 不等于任务 Runtime

Google LRO 只管理“一个控制操作的进度和结果”。本设计中的 Operation 用于安装、启停、检查、更新等控制动作，不承载 Agent 推理任务；Task 仍由 OrchestrationProvider/AgentRuntimeProvider 执行。

### SSE 不等于消息总线

CloudEvents 只规范 GUI 订阅的本地事件信封。SSE 是 Control Plane 到已鉴权 GUI 的单向状态流，不替换现有 Channel 或 Agent 消息链路，也不提供跨机器发布。

### Condition 与状态机并存

冻结枚举表达可执行状态机，Condition 表达正交、可扩展且带原因的观测。例如 Runtime 可以是 `running`，同时有 `CapabilityDegraded=True`。GUI 先使用聚合状态，再展开 Condition，不把所有异常塞进单一状态枚举。

### 原生 keystore 优先，迁移包显式加密

Docker 与 Dapr 的接口表明凭据后端应可替换。Windows 首版优先系统原生安全存储；跨机迁移不能假设系统 keystore 可直接复制，必须由 CredentialProvider 在用户确认后生成独立加密包并在目标端重新封装。

## 2026-08-04 受管运行窄调研

| 官方资料 | 本项目结论 |
|---|---|
| [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) | Job Object 可统一约束进程树，但本切片已有可验证的 psutil 进程树终止；Job Object 保留为加固，不为此引入新服务框架 |
| [GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes) 与 [Process Information](https://learn.microsoft.com/en-us/windows/win32/procthread/process-information) | PID 必须与创建时间、路径、SHA256 和命令摘要联合验证，不使用单独 PID 文件 |
| [GetExtendedTcpTable](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable) | Windows 可提供 TCP 端口到 PID 映射；当前复用已有 psutil 封装，无法证明 IPv6 时返回 unknown/unsupported |
| [Process Creation Flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags) | 使用 CREATE_NO_WINDOW 与 CREATE_NEW_PROCESS_GROUP，不起可见黑窗，不通过 shell 拼接命令 |
| [MoveFileEx](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexa) 与 [ReplaceFile](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilea) | 不自行封装 Win32 替换 API；在同卷同目录使用 Python `os.replace`、fsync、备份与回滚 |
| [Python os.replace](https://docs.python.org/3/library/os.html#os.replace) 与 [subprocess](https://docs.python.org/3/library/subprocess.html) | 标准库已满足原子替换和参数数组/shell=False 启动，不新增依赖 |
| [CredRead](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credreadw)、[CredWrite](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew) 与 Python keyring Windows backend | 小型 Secret 使用当前用户 Windows Credential Manager；运行时必须确认 backend_class 为 keyring.backends.Windows.WinVaultKeyring，禁止明文文件回退 |
| [cc-connect 锁定源码](https://github.com/chenhg5/cc-connect/tree/fc315d213b49d62e9d90ea4a510189d4115e636f) | 官方 CLI 支持 `-config`，Config.Load 支持 `${NAME}` 环境变量替换，合法 Schema 要求 Project/Agent/Platform；management API 使用 Bearer 但无 bind host，Telegram options 无 Group Chat 白名单，deep health 无官方端点 |
| [CC Switch](https://github.com/farion1231/cc-switch) | 只采用公开可执行文件检测和普通打开；深链导入仍需 UI 确认，不把私有存储或 GUI 自动化当成稳定 API |

## 2026-08-05 Telegram 与 Secret 窄调研结论

未引入完整 Telegram Bot Framework、Vault、Redis、Celery 或工作流引擎。Telegram Bot API 只实现 getMe、getWebhookInfo、getUpdates 和显式 deleteWebhook；重试仅处理有界 429，长轮询可取消，Token 不进入结构化错误。一次性绑定采用标准库 secrets、HMAC 与 SQLite revision/offset，不复制第三方认证系统。锁定 cc-connect 的环境变量替换由精确 commit 源码、上游测试与外部 Go 探针共同证明，构建仍使用既有 patchset 0.1，没有新增 Patch 或依赖。

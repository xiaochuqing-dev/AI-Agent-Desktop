# 02 Control Plane 边界

## 一句话定义

Local Control Plane 是单用户桌面产品的后台管理进程：它通过 Adapter 发现和管理成熟外部组件，维护产品级状态与操作日志，并向 GUI 提供唯一稳定 API。它不执行 Agent 的模型推理，也不代替上游编排与消息通道。

## 负责范围

1. 发现本机组件、版本、能力与依赖。
2. 维护安装、配置、授权、运行、健康、更新与管理权状态。
3. 调用 LifecycleProvider 完成受控安装、启停、健康、更新、备份、回滚与迁移。
4. 通过 Provider 描述符和 CapabilityRegistry 做能力与契约版本协商。
5. 通过 ModelConfigurationProvider 和 CredentialProvider 实施唯一写入权与 Secret 分离。
6. 接收 GUI 或 Channel Adapter 归一化的人类控制指令，交给 HumanControlPolicy 串行化。
7. 提供版本化本地 API、异步 Operation、SSE 事件、诊断和脱敏日志。
8. 保存产品自身的期望状态、Adapter 映射、资源版本、操作记录与恢复点索引。
9. 将上游技术错误转换成用户能理解的状态与建议，同时保留受控技术诊断。

## 不负责范围

- 不替代 OrchestrationProvider 决定智能任务内容。
- 不运行第二套 Agent Runtime、消息总线或通用工作流引擎。
- 不解析某个 Channel 的专属消息对象；Channel Adapter 完成映射。
- 不直接编辑非本应用所有的配置或官方登录凭据。
- 不把 GUI 状态当成事实源，也不依赖 GUI 生命周期。
- 不保证外部进程支持强暂停或强取消；能力不足时必须如实返回。
- 不持久化普通聊天正文作为产品管理所必需的数据。
- 不在 v1 装载任意第三方代码或提供插件市场。

## 进程与调用方向

```text
PySide6 GUI（可退出、可替换）
        |
        | loopback HTTP/JSON + SSE，Bearer 鉴权
        v
Local Control Plane（独立用户级后台进程）
        |
        | 仅调用冻结的 Provider/Policy 端口
        v
Adapter（当前组件的翻译与防腐层）
        |
        | 上游公开接口、CLI、受控配置或现有脚本
        v
外部组件与现有 Reference Baseline
```

禁止反向依赖：Adapter 不 import GUI；外部组件不依赖 Control Plane 领域对象；GUI 不读取 Adapter 私有文件。事件由下向上报告事实，但不改变依赖方向。

当前实现补充：PySide6 GUI 位于 `control-plane/control_plane/gui/`，包含 Demo、HTTP/Bearer 和 Embedded Control Plane 客户端。Demo 只用于显式离线截图/测试，标题栏显示预览模式；默认真实模式使用 Embedded Control Plane，并以 Control Plane snapshot 和 Operation 为事实源。新 GUI 私聊/群自动检测尚未用户 live 验证，状态为 `PENDING USER LIVE VALIDATION`。

## GUI 关闭后的生命周期

1. GUI 启动时读取仅当前用户可读的服务发现记录并连接 Control Plane；若服务未运行，调用独立 launcher 启动。
2. GUI 与 Control Plane 不共享进程、事件循环、数据库连接或 QWidget 对象。
3. GUI 关闭时只关闭 HTTP/SSE 客户端；不发送组件停止命令，也不结束 Control Plane。
4. Control Plane 继续监督已托管的后台服务、完成不可中断的安全阶段并记录 Operation。
5. 用户重新打开 GUI 后先读取状态快照，再从事件游标继续；游标过期时执行全量重同步。
6. 只有显式“停止团队”操作停止受管组件；“退出后台管理服务”是单独的高级操作，并在存在运行中 Operation 时拒绝或要求确认。
7. Windows 注销或关机由宿主生命周期处理：停止接收新操作，给可取消操作发送取消请求，持久化最终状态，不伪造外部进程已停止。

## 持久化边界

Control Plane 拥有：

- 组件与 Provider 描述符的缓存及最后观测时间
- 期望配置的非 Secret 部分、schema 版本、revision 和 ManagementOwner
- Operation、进度、幂等记录、资源版本和事件游标
- Diagnostic 索引、脱敏日志索引、备份与迁移清单
- Adapter 私有引用到通用 ID 的映射；该映射不进入稳定 API

Control Plane 不拥有：

- 官方登录产生的凭据文件
- 外部管理方拥有的配置内容
- 上游内部 Session 数据库及其 schema
- Channel 平台专属对象
- Reference Baseline 的历史证据

Secret 存在 CredentialProvider 的受控存储中。产品元数据只保存不可逆摘要、用途、更新时间和 `credential_ref`，不保存明文。

## 权限边界

- 默认以当前桌面用户身份运行；不长期持有管理员权限。
- 只有明确需要系统级变更的单个 Operation 触发 UAC，提权 helper 接受有限、签名或固定参数的命令，不接受任意 shell 字符串。
- API Bearer 凭据与服务发现文件使用当前用户 ACL；其他本地用户无权读取。
- GUI 永远不能通过 API 取回 Secret 明文；Adapter 使用短生命周期租约或受控注入。
- 外部管理配置只读；Owner 不匹配时写操作返回冲突。
- 日志与诊断执行字段级脱敏，原始异常也不得包含 Secret。

## 网络边界与默认传输

v1 默认使用 loopback HTTP/1.1 JSON API，并在同一端点提供 SSE：

- 仅绑定 `127.0.0.1`；是否同时绑定 `::1` 由实现评审决定，绝不绑定通配地址。
- 服务端校验 Host，拒绝非 loopback Host；浏览器来源请求默认拒绝，只有明确的本地 GUI Origin 可加入精确白名单。
- 每次启动或安装生成高熵本地 API token，通过 `Authorization: Bearer` 传递；禁止 URL query。
- 服务发现记录只含端口、进程实例 ID、API 版本和 token 引用，不含真实 token。
- v1 不需要 WebSocket：命令走 HTTP，服务端单向事件走 SSE，减少重连和双向状态复杂度。
- Windows named pipe 是未来可选 IPC 传输。它必须承载同一资源、Operation 与事件语义，不能形成第二套业务 API。

## Adapter 边界

Adapter 的职责是防腐与翻译：

- 把上游状态映射为冻结枚举和 Condition。
- 把通用命令转为上游公开接口、CLI 或当前受控脚本调用。
- 把上游专属 ID 保留在 Adapter 私有映射中，对核心只返回通用 ID。
- 声明真实能力等级，如 `read_only`、`best_effort_cancel`、`strong_cancel`。
- 对超时、退出码与非结构化输出做分类，不向 GUI 泄露原始复杂度。

Adapter 不得偷偷补齐上游不具备的能力。能力缺失返回 `unsupported`；读不到状态返回 `unknown`，不能猜测。

## Windows-first 与跨平台约束

Windows 首版可以使用用户级后台宿主、UAC helper、Windows Credential Manager 或 DPAPI、Job Object 和 named pipe 等实现。但领域模型、Provider 契约、OpenAPI、事件信封、路径模型与管理权状态机不得出现 Windows 专属字段。

跨平台替换点为：HostLifecycle、PrivilegeBroker、CredentialBackend、PathResolver、ProcessInspector 与 LocalTransport。更换这些 Adapter 不改变 GUI API，也不要求迁移上游 Agent 的业务逻辑。

## 故障隔离

- 一个 Adapter 崩溃只使其 Provider `degraded/error`，Control Plane 与其他 Provider 保持可用。
- Control Plane 重启后从持久化 Operation 和实际组件探测重建状态；不自动重放可能产生副作用的请求。
- GUI 不可达不影响后台；SSE 断开不取消 Operation。
- 外部组件状态与期望状态不一致时显示 `drift` Condition，先诊断再由用户决定接管、接受或回滚。

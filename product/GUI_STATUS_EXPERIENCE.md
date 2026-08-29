GUI 状态体验模型 GUI_STATUS_EXPERIENCE

本文档同时记录正式 GUI 的目标体验与当前 `0.4.1-prebeta` 实现。真实 Agent Detection、严格 Runtime Readiness、Binding/Live 分离、Hermes Telegram Native Onboarding 和 Live E2E GUI 已接入，但完整发布体验和真实 Telegram 复测尚未完成。
GUI 是 Control Plane 状态的视图，不是状态所有者。它只通过稳定本地 API 读取 StateSnapshot 和下发 Operation，不直接读取上游目录、进程或配置。
关闭 GUI 只断开本地客户端，不能停止 Control Plane 或已经运行的 Agent/Channel 服务。

当前实现映射
------------

`control-plane/control_plane/gui/` 提供 Welcome、统一四步 Wizard Shell、Token、私聊 deep link/QR、同群检测、Agent/Runtime/Chat Health、Hermes readiness/conflict、Live E2E、Dashboard、Diagnostics、刷新和 Demo。正式 SVG IconRegistry、Design Tokens、TitleBar 和 GlassDialog 统一用户可见控件。Agent 状态来自 Detector，Bot Identity 只用于 Telegram；配置完成只有在严格 Runtime Ready 时成立。`DemoControlPlaneClient` 只用于截图和自动化测试。

当前证据状态：新 GUI 私聊激活和群自动检测为 `PENDING USER LIVE VALIDATION`；Windows 10 x64 为 `PENDING WINDOWS 10 VALIDATION`；MSI、正式安装器和代码签名为 `DEFERRED`。历史直接 Telegram 六链路确认与新 GUI 证据严格分开。

一、状态数据来源

每个组件分别保留六个正交状态：
InstallationState：安装状态
ConfigurationState：配置状态
AuthenticationState：授权状态
RuntimeState：运行状态
HealthState：健康状态
UpdateState：更新状态

Control Plane 按冻结规则生成 user_status，GUI 不自行猜测。update_available、operation_in_progress、drift_detected 和 restart_required 可以作为叠加状态出现。
当 observed_generation 落后、Control Plane 不可达或 Adapter 无法可靠观测时，GUI 显示“状态待确认”，保留上次观测时间，但不得显示虚假绿色。

二、错误与诊断显示

默认层只显示普通用户能理解的说明、受影响能力和下一步操作。
“查看详细诊断”展开稳定错误码、观测时间、相关组件和已经脱敏的技术信息。
GUI 不显示 Secret、Authorization、配置正文、聊天正文、私有绝对路径或未清理堆栈。
一个可选组件异常时，正常能力保持可用，不把整个系统误报为失败。

三、十个主要状态

1. 未安装 not_installed

触发：必需组件 InstallationState=not_installed。
看到：缺失组件、环境检测摘要和预计影响。
操作：开始安装、重新检测、查看前置要求。
恢复：安装 Operation 成功后进入已安装未配置；失败保留已完成步骤和诊断。

2. 已安装未配置 installed_unconfigured

触发：组件已安装，ConfigurationState=missing。
看到：待配置项目、缺失原因、当前版本；不显示内部文件位置。
操作：进入模型配置、账号授权或 Channel 配置；重新校验。
恢复：配置通过后根据授权与运行状态进入需要登录、正在启动或已停止。

3. 需要登录 login_required

触发：AuthenticationState=required、expired 或 invalid。
看到：需要处理的账号、状态原因和官方登录入口；不展示登录材料。
操作：发起官方登录、刷新状态、选择受支持的自定义 API 路线、跳过可选 Agent。
恢复：授权成功后进入已停止或正在启动；跳过必需项时保持阻断，跳过可选项时进入部分能力异常。

4. 配置无效 configuration_invalid

触发：ConfigurationState=invalid 或 conflict。
看到：字段级安全摘要、管理方冲突或漂移原因、可用备份。
操作：修正候选配置、选择唯一 ManagementOwner、只读重验、回滚。
恢复：原子提交并重新观测为 valid 后离开；校验候选不会破坏当前有效配置。

5. 正在启动 starting

触发：RuntimeState=starting 或 restarting，或相关启动 Operation 正在运行。
看到：稳定阶段、已完成项、当前等待项和是否已经越过不可逆点。
操作：查看脱敏日志、请求取消。取消按钮只表示“请求取消”，不能提前显示“已停止”。
恢复：全部必需组件就绪后进入运行正常；部分失败进入部分能力异常或启动失败；确认停止后进入已停止。

6. 运行正常 running_healthy

触发：所有必需组件 RuntimeState=running 且 HealthState=healthy，关键 Capability 可用。
看到：组件、Agent、Channel、模型管理方和最近健康观测摘要。
操作：健康检查、查看日志、停止、重启、打开配置；只有 Capability 支持的操作才可用。
恢复：局部异常进入部分能力异常；发现更新时显示更新可用；用户停止后进入已停止。

7. 部分能力异常 partially_degraded

触发：核心仍可运行，但某个可选组件、Agent、Channel、Condition 或 Capability degraded/unavailable。
看到：正常能力与受影响能力分开列出，给出具体影响和恢复建议。
操作：针对异常项检查、重启或查看诊断；继续使用正常部分。
恢复：全部关键条件恢复后进入运行正常；必需运行链路失败时进入启动失败或已停止。

8. 更新可用 update_available

触发：UpdateState=update_available，且没有优先级更高的阻断状态。存在阻断时只显示 update_available 叠加标记。
看到：当前版本、候选版本、兼容性、回滚点要求和预计影响。
操作：延后、查看变更、创建备份后更新。
恢复：更新 Operation 期间显示进度；成功后重新健康检查；失败时提供回滚。

9. 启动失败 start_failed

触发：RuntimeState=failed，必需组件无法进入运行状态。
看到：失败组件、用户说明、恢复动作和最近一次可靠状态。
操作：只读诊断、修复配置、重试、恢复旧生命周期所有权或回滚。
恢复：重试成功后进入运行正常或部分能力异常；用户停止后进入已停止。

10. 已停止 stopped

触发：RuntimeState=stopped，且没有安装、配置或授权阻断。
看到：停止原因、上次运行状态和配置/授权摘要。
操作：启动、修改配置、健康预检、查看历史诊断。
恢复：启动请求进入正在启动；重复停止是成功 no-op。

四、Operation 与事件体验

所有外部变更使用 Operation。GUI 显示“请求已接受”“正在执行”“请求取消”“已完成”“失败”“已取消”这些不同阶段。
HTTP 超时或 SSE 断开不等于操作失败，也不取消后台工作。GUI 使用相同 idempotency key 查询或重试，并在重连后按事件 ID 去重。
事件游标过期时，GUI 先重新获取完整状态快照，再建立新订阅，不能用旧事件覆盖新 revision。

五、技术方向

正式 GUI 当前实现为 PySide6 + Qt Widgets + QSS。视觉资源、主题和动画只属于表现层；业务规则、状态聚合、凭据和 Provider 调用全部留在 Control Plane。新 GUI 的实现通过本地自动化测试，但未经用户真实 Telegram 复测；更换 GUI 技术栈不应改变本状态语义。

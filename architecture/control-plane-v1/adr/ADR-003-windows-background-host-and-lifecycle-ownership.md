ADR-003 Windows 后台宿主与生命周期所有权
=========================================

状态: Accepted / Frozen
日期: 2026-07-31

上下文
------

当前 Reference Baseline 的生命周期由现有脚本拥有:Hermes_Gateway.vbs / Hermes_Gateway.cmd / Hermes_Gateway_Watchdog.vbs、CcConnect_Autostart.vbs / cc_connect_autostart.py、计划任务 Hermes_Gateway 与 Hermes_Gateway_Watchdog。这些是当前真实的生命周期所有者。

契约与提示词要求:09 §62-69 生命周期接管分 shadow plan 与 controlled takeover 两个小门禁,未通过门禁时 API 返回 CAPABILITY_UNSUPPORTED,不得调用现有脚本冒充实现;旧计划任务、Watchdog 与 Control Plane 不能同时拥有启动权(双 supervisor 禁止);本阶段先观测、后接管,只读发现 + dry-run 计划,不要求真实安装、登录、启动、停止、更新或发送消息;GUI 关闭后后台继续运行。

提示词默认推荐:后续使用成熟 Windows Service Wrapper,而不是自行编写服务管理框架。

决策
----

1. 本阶段 Control Plane 以开发态前台进程运行(uvicorn 绑定 127.0.0.1),不注册计划任务、不安装 Windows 服务、不接管任何现有 Watchdog 或启动脚本。
2. 现有 Hermes_Gateway、Watchdog、CcConnect_Autostart 与计划任务保持为唯一生命周期所有者,Control Plane 对它们只做只读发现与状态观测,不停止、不重启、不修改。
3. 生命周期接管在本阶段只产出 dry-run 计划(shadow plan):识别现有启动所有者、目标进程、依赖、命令与预期结果,只生成计划不执行。start/stop/restart/install 端点在本阶段返回 CAPABILITY_UNSUPPORTED。
4. 未来 Windows 后台宿主方向:采用成熟 Windows Service Wrapper(候选:NSSM、pywin32 服务、或受控的 schtasks 封装),不自行编写服务管理框架;在 controlled takeover 门禁通过前不落地任何服务化实现。
5. Control Plane 退出不影响任何已运行组件与现有生命周期脚本;Control Plane 自身可完全退出,旧启动所有权不变。

替代方案
--------

A. 本阶段就用 schtasks 或 pywin32 注册服务并接管:违反“先观测后接管”门禁,且会与现有 Watchdog 形成双 supervisor,风险最高(10 §21 风险登记第 1 条)。不采用。

B. 自行编写 Windows Service 管理框架:违反“不重复造轮子”(提示词禁止自行实现 Windows 服务包装器)。不采用。

C. 用 Control Plane 直接拉起现有脚本替代 Watchdog:未通过 controlled takeover 门禁前禁止,且破坏非回归(现有链路继续按原所有权运行)。不采用。

后果
----

正面:
- 零双 supervisor 风险,Reference Baseline 运行态完全不受影响。
- 本阶段 Control Plane 纯增量,可随时退出,无需回滚现有服务。
- 为未来 controlled takeover 积累 shadow plan 证据。

负面 / 约束:
- 本阶段无法通过 Control Plane 真正启停组件,只能观测与计划。这是切片刻意边界,不是缺陷。
- 未来服务化需在 controlled takeover 门禁通过后单独评估,本 ADR 不承诺具体 Service Wrapper 选型,只承诺“成熟方案、不自实现”。

回退条件
--------

1. Control Plane 前台进程在 Windows loopback 上无法稳定常驻(uvicorn 异常退出无法解释)。
2. 只读发现行为意外触发现有 Watchdog 或计划任务的状态变更(双写或拉起)。
3. shadow plan 采集现有启动所有者信息时侵入到需提权或需修改系统的范围。

回退路径:Control Plane 进程直接退出,不遗留任何注册项、计划任务或服务;现有生命周期脚本未被修改,回滚为零成本。

未来重审触发器
----------------

1. 某组件通过 controlled takeover 门禁(隔离回归 + 备份旧启动定义 + 用户显式确认),需为该组件启用真实 start/stop/restart。
2. 评估正式 Windows Service Wrapper 选型(阶段 3 安装与更新前)。
3. GUI 无头运行验收要求 Control Plane 随用户登录自启动。

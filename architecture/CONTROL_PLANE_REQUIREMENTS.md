Control Plane 架构契约需求文档

文档定位: 本文档定义 Control Plane 的定位、目标、必要性、与参考实现的关系、
本阶段产出范围与明确不做的事项。本文档是需求契约，不含实现代码。
涉及真实凭据或本机路径处一律使用占位符，不出现真实值。

一、定位

Control Plane 是本应用的统一编排中枢。它不直接实现任何单一组件的业务逻辑，
而是通过 Provider 契约组合多个成熟组件，向上为 GUI 层提供稳定的本地 API。

Control Plane 处于 GUI 与底层组件之间，是二者之间的唯一契约层。GUI 不直接调用
Hermes、cc-connect、Telegram 等组件的内部接口，只依赖 Control Plane 暴露的
本地 API。底层组件升级、替换或并存时，只要仍满足 Provider 契约，GUI 无需改动。

二、目标

1. 屏蔽组件差异，向 GUI 提供一致的调用接口。
2. 解耦 GUI 与具体组件实现，组件可被等价实现替换而不影响上层。
3. 统一管理 Agent 生命周期、通道、编排流程、能力注册四类控制面。
4. 提供人类控制入口，保证人类干预具有最高优先级。
5. 收敛当前散落在 webhook、relay、启动脚本里的控制点为稳定契约。

三、为什么需要 Control Plane

当前参考实现中 Hermes、cc-connect、Telegram 三者通过硬编码的 webhook 回调、
relay 调用、VBS 启动脚本耦合在一起。GUI 若想知道某个 Agent 是否在线、想暂停
某个编排、想接入新通道，没有统一入口，只能各自对接组件私有接口。

Control Plane 把这些散落的控制点收敛成稳定契约。没有它，每新增一个通道或替换
一个组件，GUI 都要重写对接逻辑；有了它，GUI 只对接 Control Plane 一处。

四、与参考实现的关系

1. 当前参考实现基于 Hermes（编排）、cc-connect（Agent 运行时）、Telegram（通道）
   三者组合，由 dual_agent 模块提供并行与顺序编排回退。
2. Control Plane 契约描述的是这组组合对外应暴露的能力，不绑定三者内部实现。
3. 参考实现是 Control Plane 契约的第一个具体实现，后续可被等价组件替换。
4. 契约文档中不出现具体组件名作为能力定义，仅在映射说明处标注当前映射关系。

五、组合模式与 Provider 契约

Control Plane 通过五类 Provider 契约组合组件，每类契约只规定能力边界与调用约定：

1. OrchestrationProvider：编排能力，当前映射 Hermes。
2. AgentRuntimeProvider：Agent 运行时能力，当前映射 cc-connect。
3. ChannelProvider：消息通道能力，当前映射 Telegram 与 Hermes Telegram Platform。
4. LifecycleProvider：安装、启动、停止、重启、健康、更新、回滚、迁移。
5. CapabilityRegistry：Agent 注册与能力检测。

每个 Provider 契约明确职责、能力边界、不绑定什么、未来如何被替代，详见
PROVIDER_CONTRACT_REQUIREMENTS.md。

六、稳定本地 API

1. 通过 HTTP 与 IPC 两种方式暴露，均只绑定 localhost，不对外网开放。
2. API 版本化，新增能力走版本协商，旧 GUI 不被破坏。
3. GUI 只依赖此 API，组件替换时 API 保持稳定。
4. API 能力清单覆盖：Agent 在线状态、编排控制、通道收发、生命周期操作、
   能力查询、人类控制指令。

七、本阶段产出

1. 五类 Provider 契约需求文档。
2. 通用通道模型需求文档。
3. 人类控制需求文档。
4. 模型配置管理边界文档。
5. 凭据管理边界文档。
6. Control Plane 本地 API 的能力清单（只定义，不实现运行时代码）。

八、不做的事

1. 不实现 Control Plane 的运行时代码。
2. 不替换当前参考实现的 Hermes、cc-connect、Telegram 组件。
3. 不绑定任何单一组件的内部数据结构或私有 API。
4. 不引入新的外部依赖组件（本阶段）。
5. 不在文档中写入真实 Token、API Key、Bearer、真实用户标识或真实绝对路径，
   一律使用占位符如 <TELEGRAM_BOT_TOKEN>、<WINDOWS_USER>、<PROJECT_ROOT>。

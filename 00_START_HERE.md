00 开始阅读
============

本仓库是当前公开事实源。请按以下顺序阅读。

一、先读这些
--------------
1. README.md（本仓库是什么）
2. 01_CURRENT_STATE.md（当前真实状态）
3. 02_PRODUCT_VISION.md（产品愿景与十分钟目标）
4. 03_LATEST_PRODUCT_DECISIONS.md（最新产品决策）
5. CURRENT_RUNTIME_SOURCE_MAP.md（当前运行源码与 Git 的对齐核验）
6. reference-baseline/SOURCE_OF_TRUTH.md（事实源优先级）
7. 04_REFERENCE_BASELINE.md（参考基线）
8. architecture/control-plane-v1/README.md（Control Plane v1 正式设计包与阅读顺序）
9. contracts/control-plane-v1/control-plane.openapi.yaml（本地 API 机器契约）
10. contracts/control-plane-v1/core-models.schema.json（核心领域模型）
11. contracts/control-plane-v1/event-envelope.schema.json（统一事件信封）
12. 05_NEXT_PHASE.md（下一阶段）

二、src/ 是什么
---------------
src/ 保存的是与当前运行体对齐的源码。修改 src/ 就是在修改当前真实集成的代码。
- src/hermes-adapter/   Hermes multiagent 适配层（config/orchestrator/_planner/policy 等）
- src/dual-agent-fallback/   dual_agent 包（并行/顺序/聚合/防重复纯逻辑）
- src/lifecycle/   启动脚本（Hermes Gateway、cc-connect autostart、junction 工具）

三、旧报告不是事实源
---------------------
history-minimal/ 只是有长期价值的历史摘要，不是当前事实源。
当前事实源以本目录根文档、reference-baseline/、src/ 为准。

四、下一阶段
------------
审阅并冻结 Control Plane v1 契约，然后实现第一个最小纵向切片。
Control Plane v1 设计包是架构事实源，机器可读契约是接口和模型评审依据；二者都不能覆盖当前运行事实。
实现只从发现、状态、能力、只读配置校验、受控生命周期、健康与脱敏诊断开始，不直接改运行环境，不重启当前服务，不开发正式 GUI。
见 next-agent/NEXT_AGENT_PROMPT.txt。

五、遇到矛盾
------------
以实际文件、Git、SHA256 为准。停下报告，不猜测。

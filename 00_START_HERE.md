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
8. 05_NEXT_PHASE.md（下一阶段）

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
独立 Control Plane 与 Provider/Adapter 契约设计。
第一轮只做分析和设计，不直接改运行环境，不重启服务，不开发 GUI。
见 next-agent/NEXT_AGENT_PROMPT.txt。

五、遇到矛盾
------------
以实际文件、Git、SHA256 为准。停下报告，不猜测。

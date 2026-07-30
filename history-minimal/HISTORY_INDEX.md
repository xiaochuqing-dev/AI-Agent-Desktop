历史索引（精简版）
==================

本目录只保留有长期价值的历史摘要。旧中间报告不进入主阅读路径。

一、阶段划分
------------
Step 0（2026-07-27）: 现场安全冻结与工程资产采集
Step 1（2026-07-27）: 版本库初始化与资产收集
Step 1.5（2026-07-27）: Patch 文件化、构建固化、PII sanitize、测试修正
Step 2（2026-07-28）: 候选首次切换，发现双 Agent 异常
Step 2 A/B 对照（2026-07-28）: 证明根因在 Hermes 适配层，非候选或 Patch
Step 2 修复（2026-07-28）: 两层修复（dual_agent 配置化 + planner 顺序识别）
Step 2D（2026-07-28）: 候选复测全部通过，冻结 v0.1-reference-baseline

二、关键决策
------------
1. 候选结论更正为 E2E INCONCLUSIVE - CONFOUNDED BY HERMES ADAPTER MISCONFIGURATION
2. dual_agent 路径解析配置优先，不依赖环境变量偶然继承
3. parallel/sequential 禁止静默降级，fail-fast
4. planner 靠 LLM 语义理解，不加关键词规则
5. reference baseline 冻结后进入 Control Plane 契约设计

三、历史摘要文件
----------------
selected-final-summaries/ 下保留关键阶段摘要。
这些是历史证据，不是当前事实源。当前事实源以根目录和 reference-baseline/ 为准。

四、过时结论
------------
以下旧结论已失效，不得作为当前事实:
- 候选尚未切换（已切换）
- 当前仍运行旧 cc-connect（已切换为候选）
- dual_agent 仍未加载（已修复）
- 顺序任务仍失败（已修复）
- 尚未完成 Telegram E2E（已完成）
- 旧 Bundle 是最终源码（已淘汰，以 Git 为准）

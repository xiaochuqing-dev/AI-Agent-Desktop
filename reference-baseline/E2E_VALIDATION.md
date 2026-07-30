E2E 验证
========

验收日期: 2026-07-28
结论: REAL TELEGRAM GROUP AND HERMES PRIVATE CHAT E2E VALIDATED

群聊通过（9 项）
1. 普通群消息静默
2. 直接 @Hermes 只 Hermes 回
3. 直接 @Claude 只 Claude 回
4. 直接 @Codex 只 Codex 回
5. Hermes -> Claude 单 Agent
6. Hermes -> Codex 单 Agent
7. Reply A + @B 只 B 回
8. 双 Agent 独立并行（走 run_parallel，不进 legacy，Worker 不越界，Hermes 只总结一次）
9. 双 Agent 顺序传递（走 run_sequential，不进 legacy，内部 handoff 不公开，Hermes 只总结一次）

Hermes 私聊通过（3 项）
1. 私聊无需 @ 只回复一次
2. 私聊普通问题正常单向响应
3. 群聊与私聊不串线

候选结论更正
  早期 PARTIAL FAILURE 经 A/B 对照证明根因在 Hermes 适配层。
  更正为 E2E INCONCLUSIVE - CONFOUNDED BY HERMES ADAPTER MISCONFIGURATION。
  修复后全部通过。

尚未验证或未实现
  讨论模式、插话/暂停/取消/改派、Claude<->Codex 互调、飞书等新渠道、GUI、Control Plane、EXECUTION 真实 E2E、Session 6h、@all 广播。

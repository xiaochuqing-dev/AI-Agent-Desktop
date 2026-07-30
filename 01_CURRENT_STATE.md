01 当前状态
============

生成时间: 2026-07-30

一、reference baseline
-----------------------
Git Tag: v0.1-reference-baseline
baseline 仓库（私有，不在本公开仓库）: C:\ai-agent-collaboration-baseline
baseline HEAD: cd3493b191fdc19114e0ae037746ab3d23a58a79
公开仓库 src/ 与该 HEAD 对齐（见 CURRENT_RUNTIME_SOURCE_MAP.md）。

二、当前运行 cc-connect
------------------------
版本: v1.4.1-patchset0.1-fc315d2
SHA256: f7a577bba84bf732519d98cfdf70fa6c089fbc50ae9e14deb775d3c46d0409fb
上游 Commit: fc315d213b49d62e9d90ea4a510189d4115e636f
Patch-set: 0.1，5 个 Patch（见 integrations/cc-connect/patches/）

三、Hermes 适配层修复
----------------------
已合入 baseline HEAD cd3493b，公开仓库 src/ 已对齐:
- 第一层 383375d: config.py dual_agent_root 配置化解析（env > config > junction > fail-fast），parallel/sequential 禁止静默降级
- 第二层 cd3493b: _planner.py 强化顺序意图理解，强制多 Agent 时 tasks 不能为空

四、已通过的真实 E2E
---------------------
群聊（9 项）: 普通静默、@Hermes、@Claude、@Codex、单Agent Claude、单Agent Codex、Reply+@、双Agent并行、双Agent顺序
Hermes 私聊（3 项）: 无需@只回复、普通问题正常、群聊私聊不串线

五、候选结论更正
----------------
早期候选 PARTIAL FAILURE 经 A/B 对照证明根因在 Hermes 适配层，非候选或 Patch。
更正为: E2E INCONCLUSIVE - CONFOUNDED BY HERMES ADAPTER MISCONFIGURATION。
修复后全部通过。

六、尚未实现
------------
讨论模式、插话/暂停/取消/改派、Claude<->Codex 互调、飞书等新渠道、GUI、Control Plane、EXECUTION 真实 E2E、Session 6h、@all 广播。

七、当前未进入
--------------
Control Plane 编码、GUI 开发、GUI 技术栈选型。

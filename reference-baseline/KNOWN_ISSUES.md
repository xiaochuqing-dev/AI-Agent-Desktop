已知问题
========

生成时间: 2026-07-30

已解决
1. dual_agent 未加载导致并行/顺序降级 legacy - 已修复（config.py 配置化解析）
2. planner 顺序识别错误导致走并行退化 - 已修复（_planner.py 强化语义理解）
3. Watchdog 启动链不设 AI_AGENT_COLLAB_ROOT - 已修复（Watchdog vbs 防御性传递 + config 兜底）
4. parallel/sequential 静默降级 - 已修复（orchestrator fail-fast）

未解决（不阻塞参考基线）
1. 讨论模式（DISCUSS）未真实 E2E
2. 用户插话、暂停、取消、改派未实现
3. Claude<->Codex 互调未实现
4. Telegram 之外的渠道不在首发产品范围
5. GUI 未开发
6. Control Plane 真实安装、配置写入、凭据写入与生命周期接管未实现；只读基础运行代码已实现
7. EXECUTION 模式未真实 E2E
8. Session 6h 连续未验证
9. @all 广播未实现
10. 历史报告含真实 User ID（标记 P1，公开发布前需清理）- 本公开仓库已清理
11. /start 等命令偶尔可能未进入预期逻辑，普通消息仍可能正常
12. 私聊、群聊、Reply、Mention、Topic、Session 的完整隔离与路由矩阵尚未补齐

技术债
1. orchestrator.py 仍有 669 行 legacy 与 dual_agent 重复（P1，本轮不清理）
2. dual_agent 是临时 Fallback，Hermes 原生支持后应可删除
3. cc-connect 5 Patch 是兼容层，上游修复后应可删除

当前运行源码事实图
==================

生成时间: 2026-07-30
核验结论: CURRENT RUNTIME SOURCE VERIFIED

一、核验方法
------------
逐项对比"当前真实运行加载的代码和二进制"与"baseline Git 仓库源码"和"正式 Patch 与构建链"。
不依赖文件名猜测，用进程命令行、模块 import 路径、文件 SHA256 和运行版本确认。

二、当前运行进程
----------------
默认 Hermes Gateway:
  PID 6292
  命令行 pythonw.exe -m hermes_cli.main gateway run
  由计划任务 Hermes_Gateway 经 Hermes_Gateway.vbs 拉起
  监听 8423（multiagent hook receiver）
  加载位置 C:\Users\<WINDOWS_USER>\AppData\Local\hermes\hermes-agent\plugins\multiagent

cc-connect:
  PID 13672
  二进制路径 C:\Users\<WINDOWS_USER>\AppData\Roaming\npm\node_modules\cc-connect\bin\cc-connect.exe
  版本 v1.4.1-patchset0.1-fc315d2
  SHA256 f7a577bba84bf732519d98cfdf70fa6c089fbc50ae9e14deb775d3c46d0409fb
  由 CcConnect_Autostart.vbs 拉起

glm-coding profile: 当前未运行（不纳入本项目默认源码）

三、运行源码映射表
-------------------
| 组件 | 当前运行路径 | 当前运行版本/哈希 | 正式源码路径 | Git Commit/基础 | 一致 | 公开仓库目标路径 |

Hermes multiagent 插件（9 文件）:
  运行路径 AppData\...\plugins\multiagent\
  运行哈希 config.py D3F85DCC... / orchestrator.py 96DEF623... / _planner.py FEABA66C...
  正式源码 baseline src\hermes-multiagent\
  Git HEAD cd3493b
  一致: 是（9 文件 SHA 全部一致）
  公开目标 src/hermes-adapter/

dual_agent 包（5 文件）:
  运行路径 C:\ai-agent-collaboration\dual_agent\（junction 根）
  运行哈希 __init__.py 48E6A9E1... / runner.py 349BFB63...
  正式源码 baseline src\dual_agent\
  Git HEAD cd3493b
  一致: 是（5 文件 SHA 全部一致）
  公开目标 src/dual-agent-fallback/

启动脚本（5 文件）:
  Hermes_Gateway.vbs 运行哈希 4A54327A... = baseline 一致
  Hermes_Gateway.cmd 7953F897... = 一致
  Hermes_Gateway_Watchdog.vbs 38D4E7F4... = 一致
  CcConnect_Autostart.vbs F49F9BE7... = 一致
  cc_connect_autostart.py 43F39AD2... = 一致
  公开目标 src/lifecycle/

cc-connect 二进制:
  运行版本 v1.4.1-patchset0.1-fc315d2
  SHA256 f7a577bb...
  上游 Commit fc315d213b49d62e9d90ea4a510189d4115e636f
  Patch-set 0.1，5 个 Patch
  构建链 apply-cc-connect-patches.ps1 + build-cc-connect.ps1
  一致: 是（5 Patch SHA 与 baseline 一致）
  公开目标 integrations/cc-connect/

multiagent.yaml:
  运行路径 AppData\...\hermes\multiagent.yaml
  含真实 dual_agent_root 值（本机绝对路径）
  公开模板 config-examples/multiagent.yaml.example（占位符）
  差异性质: E（运行值 vs 占位符，正常）

四、差异分类
------------
A. 当前运行代码与最终 Git Commit 一致: 全部一致
B. 当前运行代码比旧快照新，与最终 Git Commit 一致: 旧快照已淘汰，不进公开仓库
C. 当前运行代码含有有效新修改但未进入 Git: 无
D. 最终 Git Commit 有修改但当前运行没有加载: 无
E. 差异只是 Secret/绝对路径/运行状态: multiagent.yaml 的 dual_agent_root（运行真值，公开占位）

五、关键代码行为验证（基于源码与已有 E2E，本轮不重测）
-------------------------------------------------------
1. Hermes Telegram 自己直连（gateway.py + telegram_platform adapter）
2. Claude Code 和 Codex 由 cc-connect 连接（cc-connect config.toml projects）
3. 群聊普通消息不误触发（policy.decide + skip reason=plain group message）
4. @Hermes/@Claude/@Codex 路由边界（policy.py + telegram.go isDirectedAtBot）
5. Reply A + @B 显式目标优先（Patch 001）
6. Hermes 单 Agent 委派（orchestrator._delegate_once）
7. 并行走 run_parallel（dual_agent.runner.run_parallel，不进 legacy）
8. 顺行走 run_sequential（dual_agent.runner.run_sequential，不进 legacy）
9. parallel/sequential 不静默进 legacy（orchestrator._run_delegate fail-fast）
10. Worker 不获全局主持职责（_build_parallel_message 防主持人措辞）
11. 内部 handoff 不公开（_build_step_message + dual_agent 注入前步输出）
12. Hermes 私聊不需要 @（gateway 默认私聊响应）
13. 私聊与群聊路由和 Session 隔离（policy 按 chat_id 区分）
14. dual_agent 路径解析不依赖偶然终端环境（config.resolve_dual_agent_root: env > config > junction > fail-fast）
15. Watchdog 和默认 Gateway 启动有明确源码和脚本来源（Hermes_Gateway_Watchdog.vbs + Hermes_Gateway.vbs）
16. cc-connect 5 Patch 与运行二进制可对应（fc315d2 + 5 Patch 构建出 f7a577bb）

六、结论
--------
CURRENT RUNTIME SOURCE VERIFIED
当前运行关键代码能映射到正式源码，当前运行二进制能映射到正式 Patch 与构建链，关键修复确实存在，不存在未解释的运行代码差异。
公开仓库 src/ 中的源码与当前运行体一致。

# 六链路可观测性、Live E2E 与用户验证闭环最终报告

更新时间：2026-08-07

当前状态：用户真实体验验收已通过；功能与 CI 门禁已完成，报告提交信息由 Git 和 GitHub Actions 元数据记录

总体结论：六条 Telegram 私聊/群聊链路由用户直接操作并明确确认无问题、可以通过。代码、合成验收、Windows 11 候选包和本地安全门禁均通过。由于本轮没有使用验收向导，三次真实 getMe、3/3 绑定和六条 correlation 的 Control Plane 持久化证据未采集；Windows 10 x64 也未实机验证。因此六条用户体验链路为 LIVE_VERIFIED，整体发布状态保持 PARTIAL，不能虚报 COMPLETE。

## 一、范围与三阶段流程

- 起始 main：fa9fcdaed37d44db1c4dd6311c5d98bd5c9a06bb。
- 产品方向未变：Windows 10/11、Telegram、Hermes、Claude Code、Codex；cc-connect 是 V1 核心桥梁，CC Switch 推荐但非强制。
- 阶段 A：修复正式依赖和锁定、实现代理策略、六 LinkState、一次性 E2E、消息关联、Session 隔离、候选包和向导，并完成 Fake/合成门禁。
- 阶段 B：处理向导绑定/弹窗反馈和 Hermes 黑窗口反馈；用户最终选择直接在 Telegram 完成六链路验收。
- 阶段 C：用户于 2026-08-07 明确批准通过；随后执行最终本地门禁、提交 main、推送、等待 CI 并回填本报告。

## 二、实现结果

- 正式 dependencies 包含 httpx；Python 固定为 3.12.10，生产、开发和构建依赖均使用带 hash 的锁文件。
- CI 同时验证 Windows quality、Ubuntu 核心兼容、production-only 安装和锁定 cc-connect Windows 产物。
- Telegram 网络策略固定为 direct、environment、explicit；默认不读取环境代理，显式代理认证只接受 CredentialRef，日志不输出密码，也不修改系统代理。
- 六条链路固定为 hermes.private、hermes.group、claude.private、claude.group、codex.private、codex.group，状态和证据互相独立。
- LiveE2ETestService 创建不可变计划；确认绑定 plan digest、revision 和 Idempotency-Key，每次最多发送一条，失败、超时和 429 均不自动重发。
- MessageCorrelationService 校验 Bot、link、chat hash、时间、reply-to 和唯一消费；无法证明时返回 unknown 或 ambiguous，不保存消息正文。
- SessionIsolationProbe 保持 synthetic 证据等级，覆盖私聊/群聊、Agent、User/Group/Topic、Reply/Mention、命令、重启、防重放、防重复和失败不重试矩阵。
- Hermes 作为 external runtime 只读观测；Control Plane 不安装、不升级、不读取 Token、不接管 Provider 或生命周期。

## 三、API、持久化与依赖

- OpenAPI v1 向后兼容增加六链路列表/单链路、E2E 计划/确认/取消/响应、Session 隔离和 Telegram network-policy 端点。
- Alembic 0005 新增 link_status_records、live_e2e_test_plans、live_e2e_test_runs、message_correlation_records、session_isolation_results、user_validation_sessions、user_validation_steps 和 packaged_candidate_records。
- 数据库只保存 ID、hash、revision、状态、时间、延迟、诊断码、message_id 和 correlation_id；不保存 Token、API Key、绑定码明文、代理密码、完整消息或聊天历史。
- 没有升级 cc-connect、增加 Patch、引入 Bot Framework、Redis/Celery、通用 Vault 或工作流平台。PyInstaller 只用于 Windows 候选包构建；运行时新增依赖 httpx 已纳入生产锁。

## 四、最终本地门禁

锁定 Python 3.12.10 环境结果：

- ruff check：通过。
- ruff format --check：129 files already formatted。
- mypy control_plane：83 source files，无问题。
- pytest -q：187 passed，1 skipped。
- OpenAPI 与 JSON Schema：通过。
- compileall：通过。
- production-only smoke：health_check=true，real_telegram_access=false。
- Windows PowerShell 5.1 脚本解析：通过。
- git diff --check：通过。
- Reference Baseline 路径差异：0。
- 候选包文本扫描：Secret 形态 0，消息正文关键字段 0。

唯一已知测试告警是 FastAPI TestClient 对当前 httpx 兼容层的弃用提示，不影响本轮行为；后续依赖升级需显式处理。

## 五、最终 Windows 候选包

相对路径：control-plane/dist/AI-Agent-Desktop-stage-a-windows-x64-final-20260807

版本：0.1.0-stage-a

- AI-Agent-Desktop-Validation-Wizard.exe SHA256：4ce4cbab7545cf0908def26fd4e9f2e921cbb1795cf7cbef4ee0fde56e444152。
- candidate-manifest SHA256：52271b0d0eebb75c20d0c767c8e3f083fbb7870c204eca4faca2fe35589351fb。
- payload package SHA256：974c6d6598a8e418ca809ce89d029dcfad5be390b48c83dfca36738765a1c0cc。
- cc-connect SHA256：cd1b0787709c0401a42f7c3ce5321184889adbfbf3b080190fee180afc977eec。
- Manifest 中 10 个 payload 文件逐项复核通过；EXE 为 x64 Windows GUI 子系统 2。
- --version 返回 0.1.0-stage-a；--headless 退出 0，telegram_messages_sent=0、secret_values_recorded=0、message_bodies_recorded=0。
- 当前构建与验证机器为 Windows 11；Windows 10 x64 仍为 PENDING WINDOWS 10 VALIDATION。
- 桌面“AI-Agent-Desktop 验收向导”快捷方式已指向该最终候选包。

## 六、用户验证与六链路结果

验收入口：用户直接在 Telegram 客户端向现有 Hermes、Claude Code、Codex Bot 发送私聊和群聊消息，没有从向导重新开始。

| Link ID | 结果 | 证据边界 |
|---|---|---|
| hermes.private | LIVE_VERIFIED | 用户明确确认通过；Hermes 私聊活动日志元数据辅助证明 |
| hermes.group | LIVE_VERIFIED | 用户明确确认通过；Hermes 群聊活动日志元数据辅助证明 |
| claude.private | LIVE_VERIFIED | 用户明确确认通过；日志有 message.received 与 message.sent_delivered 元数据 |
| claude.group | LIVE_VERIFIED | 用户明确确认通过；日志有 message.received 与 message.sent_delivered 元数据 |
| codex.private | LIVE_VERIFIED | 用户明确确认通过；日志有 message.received 元数据，完整收发结论来自用户确认 |
| codex.group | LIVE_VERIFIED | 用户明确确认通过；日志有 message.received 与 message.sent_delivered 元数据 |

辅助日志时间集中在 2026-08-07 12:29 至 12:38，并记录到串行委派与并行委派活动。最终报告不保存 chat ID、Token、消息正文或完整日志。

## 七、真实证据边界

- 用户没有把 Bot Token 提供给本任务，仓库和报告均不保存真实 Token。
- 本轮没有通过向导执行三次 getMe，因此“三次真实 getMe”状态为 PARTIAL，不写成已持久化完成。
- 用户使用现有私聊和群聊直接验收，没有由向导生成新的 3/3 binding session，因此“真实 3/3 绑定结构化证据”状态为 PARTIAL。
- 六条链路均有用户现场通过结论，但没有完整 plan_id、correlation_id、request/response message_id 和 latency 记录；这些字段保持未采集，不从外部日志反推。
- GUI 不作为本次用户验收入口。候选 EXE 的 headless、资源打包和无控制台属性已验证，但完整 GUI getMe/绑定流程没有在最终轮由用户重跑。

## 八、用户反馈与修复轮次

1. 用户反馈向导无法绑定和弹窗报错。候选包补齐 frozen Alembic 资源解析、windowed 标准流兼容、SQLite 句柄释放和脱敏错误处理，并重建 fix 候选；最终包的 headless、迁移资源和清理路径通过自动化验证。完整 GUI 绑定仍未作为最终验收入口。
2. 用户认为命令式向导流程过于复杂，改为直接在 Telegram 验收。该选择不改变产品安全逻辑，也不被包装成不存在的向导证据。
3. 用户反馈在 Telegram 询问 Hermes 时出现 Python/script 黑窗口。本机外部运行层改为 pythonw/VBS 隐藏启动，并给 env_probe 子进程加入 CREATE_NO_WINDOW；相关测试 15 passed，pythonw 等价窗口观测为 0。修改前备份保存在 C:\tmp\hermes-black-window-backup-20260806-110841。
4. 用户再次从 Telegram 触发 Hermes 后未再报告黑窗口，并在最终轮明确确认没有问题、可以通过。

Hermes 修复文件位于 %LOCALAPPDATA%\hermes，不属于 AI-Agent-Desktop Git 仓库；Reference Baseline、cc-connect Patch、Provider、Token、PATH、注册表和计划任务定义均未改变。

## 九、CI、Git 与回滚

- 功能实现提交 SHA：f95f84231d77cb021b68caaa1e161b2b5d140ad1。
- 首次 CI Run ID：31151662035。Windows quality、production-only 和锁定 cc-connect Windows 产物作业成功；Ubuntu 作业因误用 Windows 专用开发锁失败。
- CI 修复提交 SHA：19a640a8683010f0963027245b4d61e74fb9738c。修复仅为 Ubuntu 增加平台专用依赖锁，不改变 Windows 锁或产品行为。
- 功能最终 CI Run ID：31152224373，四个作业全部 success。
- 报告回填提交 SHA 与对应 CI Run ID：由 Git 和 GitHub Actions 提交元数据记录，报告不做自引用。
- 最终分支：main；交付时要求本地与 origin/main 一致、工作区 clean，且远端仅保留 main。

回滚方法：在 main 上按逆序使用 git revert 回退最终报告提交和功能提交，然后正常推送并等待同一 CI；禁止 reset、force push 或删除历史。Hermes 本机外部运行层如需回滚，使用上述备份目录逐文件恢复，不影响仓库历史。

## 十、最终状态与下一阶段

- 六条 Telegram 用户体验链路：LIVE_VERIFIED。
- 用户明确批准：PASS。
- Control Plane 结构化 live getMe/3/3/correlation：PARTIAL，未采集。
- Windows 11 候选包：PASS。
- Windows 10 x64：PENDING WINDOWS 10 VALIDATION。
- 正式产品 GUI：DEFERRED。
- 整体：PARTIAL；代码、候选包、用户体验和 CI 收尾已通过，但不把未验证的 Windows 10 或未采集的结构化证据写成 COMPLETE。

下一阶段为“最小 GUI、十分钟 Onboarding 与 Windows 自包含分发切片”。行为变化后必须重新请用户验收。

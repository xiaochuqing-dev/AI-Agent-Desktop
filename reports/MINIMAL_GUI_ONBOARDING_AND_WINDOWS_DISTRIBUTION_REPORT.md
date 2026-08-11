# 最小正式 GUI、四步 Onboarding 与 Windows 分发实施报告

生成日期：2026-08-11

## 1. Executive Summary

本轮在当前 GitHub `main` 事实之上完成了最小 PySide6 GUI、统一四步 Onboarding、Telegram 私聊 Deep Link、手机 QR、群聊 `startgroup` 与 `my_chat_member` 自动检测、脱敏 Onboarding/Dashboard API、Windows GUI candidate 构建脚本和 CI 门禁的工作区实现。

必须先说明三个发布边界：

1. 新的 `0.2.0-gui` Windows candidate 已在 Windows 11 x64 本地构建并通过离线 candidate validator。产物位于 `control-plane/dist/AI-Agent-Desktop-gui-windows-x64`；EXE SHA256 为 `184e10f805889a66b9923d2601956cd6395ee7120f4b9134e03160f82fc72c7e`，manifest SHA256 为 `8b0bc5fce4935be49ed40a51581169ed278a27ed189b3021da6843e19184559a`，package SHA256 为 `f528f71351acd216b027a3b09cddef1547c88bb5853509737dd003ba038a7ff4`。
2. 正式 `app_icon.png` 为 768×768 RGBA、四角透明，`app_icon.ico` 含 16/24/32/48/64/128/256 多尺寸；源资源与 PyInstaller archive 内资源字节一致，PE 图标资源和黑窗口门禁均已通过。中间裁切图标和截图未纳入 candidate。
3. 新 GUI 私聊激活和群自动检测均为 `PENDING USER LIVE VALIDATION`。Hermes 未伪报实时消息、自动配置或本轮 GUI 验证；真实 Token 也未在本轮使用。

| 项目 | 当前状态 |
|---|---|
| PySide6 Welcome、统一四步 Wizard、Dashboard、Diagnostics | COMPLETE（代码） |
| GUI Demo、Fake Telegram、离屏控件测试 | SYNTHETIC_VERIFIED |
| 私聊 `/start bind_<slot>_<code>` 与 slot 约束 | SYNTHETIC_VERIFIED |
| `my_chat_member` 群自动检测与 3/3 同群一致性 | SYNTHETIC_VERIFIED |
| 2026-08-07 旧入口六条 Telegram 链路 | LIVE_VERIFIED（历史证据） |
| 新 GUI 私聊 Start 流程 | PENDING USER LIVE VALIDATION |
| 新 GUI 群自动检测流程 | PENDING USER LIVE VALIDATION |
| 新 GUI Windows candidate | LOCAL VERIFIED：candidate、manifest、哈希、EXE smoke、PE、Qt platform、内嵌模块和敏感信息扫描通过 |
| 既有 Windows 11 cc-connect/Control Plane 普通用户验收 | LIVE_VERIFIED（不覆盖新 GUI candidate） |
| Windows 10 x64 | PENDING WINDOWS 10 VALIDATION |
| MSI、正式安装器、卸载器、代码签名 | DEFERRED |

## 2. 起点、范围与产品方向

开始分支为 `main`。开始与当前检查时的本地 `HEAD`、`origin/main` 均为：

`33652568727b6bb4b41ae84b99a1e2332eea6bce`

仓库未记录精确任务起始时刻，因此不伪造时间；实施日期为 2026-08-11。当前本地只有 `main`，远端跟踪分支只有 `origin/main`。最终提交和推送状态在第 15 节回填。

产品方向未改变：Windows 10/11、Telegram 单一首发 Channel、Hermes/Claude Code/Codex 三个固定 Agent、cc-connect 作为 Claude/Codex 的 V1 Telegram 桥梁、Control Plane 作为业务和状态所有者、CC Switch 仅为可选外部入口。未增加 Agent、Channel、通用聊天工作台、插件市场或 MTProto 用户账号登录。

本轮范围是 GUI 所需的最小逻辑收口、正式 Widgets 界面、只读快照、分发脚本与验证门禁；没有重写 Control Plane、Hermes 或 cc-connect。

## 3. 六张视觉参考的落实

用户提供的前五张 GUI 图被映射为独立 Welcome、Step 1 Token、Step 2 私聊与 QR、Step 3 同群、Step 4 完成页；第六张作为应用图标来源。界面使用真实 PySide6 Widgets，没有把截图作为页面背景。

视觉实现采用蓝紫柔和渐变、半透明白蓝玻璃卡片、淡白边框、蓝紫主按钮、柔和圆角和深蓝灰文字。主要实现值包括背景 `#E8E9FD`、`#EEF2FD`、`#D8E9FF`，普通玻璃 alpha 约 118/255，强玻璃 alpha 约 151/255，步骤栏 alpha 约 88/255，主按钮由 `#4582F9` 过渡到 `#8B5CF6`。字体优先 `Segoe UI Variable`、`Segoe UI`、`Microsoft YaHei UI`。

窗口默认 1280×720，最小 1180×680。四个步骤共用固定 Shell：左侧步骤栏 238 px、中间 `QStackedWidget`、右侧帮助栏 276 px、固定底部操作区。Welcome 独立，但进入向导后不会切换成四套不同布局。

当前 DPI 策略依赖 Qt 布局、字体与最小尺寸，不依赖 Win11 Acrylic。100%/125%/150%、最大化、长中文、Windows Shell 图标缩放仍需 candidate 实机视觉复核，因此视觉验收为 PARTIAL。

## 4. GUI 技术栈与目录

正式 GUI 使用：

- PySide6 6.7.2
- Qt Widgets
- QSS
- qrcode 8.2
- Pillow 11.3.0

主要目录职责：

- `control-plane/control_plane/gui/app.py`：进程入口、单实例、Demo/HTTP/Embedded 客户端选择、截图入口。
- `main_window.py`：Welcome、Wizard、Dashboard、Diagnostics 导航和全局事件编排。
- `pages.py`：页面级真实控件。
- `widgets.py`：渐变画布、标题栏、步骤栏、状态 Chip、QR Dialog、Telegram Launcher、异步 API Runner。
- `api_client.py`：稳定 HTTP/Bearer Control Plane 客户端、Embedded 客户端和明确标识的 Demo 客户端。
- `state_store.py`：快照缓存、刷新和一次性 binding link 的窗口内保留。
- `theme/`：颜色和 QSS。
- `assets/`：PNG/ICO 图标资源。

GUI 不直接读取上游私有配置、Telegram 数据库或 Telegram 登录状态；真实状态来自 Control Plane API。Demo 仅用于截图和自动化，不能证明 live Telegram。

## 5. Welcome 与四步 Onboarding

Welcome Page 提供四步概览、预期结果、快速配置入口和说明入口。首次启动显示 Welcome；Control Plane 已完成时进入 Dashboard；中断后根据服务端 `current_step`、binding 和 checklist 恢复，而不是信任 GUI 本地布尔值。

Step 1 使用三个密码输入框采集 Hermes、Claude Code、Codex Bot Token，支持安全粘贴、清除和按住临时显示。Token 通过 Credential API 写入 Windows Credential Manager，再复用既有 Telegram `getMe` 验证；输入框清空，Token 不进入快照、SQLite、普通配置、URL或报告。

Step 2 为三个 Bot 显示身份、激活状态、“打开 Telegram”和小型 QR 按钮。Deep Link 为短时 HTTPS `https://t.me/<username>?start=bind_<slot>_<opaque-code>`；打开时优先转换为 `tg://resolve`，不可用时回退 HTTPS，仍无法打开则进入 Telegram 官方下载页。QR 弹窗编码 HTTPS Deep Link，只显示 Bot 名称、Username、失效说明和关闭按钮，不显示 Token、User ID 或单独的绑定码。

Step 3 不提供 QR，不枚举用户群，不要求输入 Group ID。页面提供打开 Telegram、逐 Bot `startgroup` 链接、复制 Username 和重新检测。三 Bot 必须由同一 operator 加入同一 `group`/`supergroup`，channel 被拒绝。

Step 4 通过现有计划化 API 检查或准备锁定 cc-connect、产品 ownership 和 Claude/Codex native configuration。写入仍受 plan ID、digest、revision、Idempotency-Key、备份、原子替换和回滚约束。当前 Step 4 不等于 Hermes 自动配置完成，也不等于六条真实消息已验证。

用户在正常路径中只需要创建三个 Bot、粘贴 Token、在三个私聊点击 Start、创建/选择一个群并加入三个 Bot；User ID、Group ID、offset、lease、owner、端口、SecretRef 和配置 revision 不在默认 UI 暴露。

## 6. Telegram 逻辑收口

私聊绑定增加了 slot 标记，避免把 Claude 的链接用于 Hermes。服务端数据库只保存 `HMAC(session_id, code)` digest，明文只在创建响应中用于生成一次性链接。旧 `/bind` 仍作为兼容恢复路径，默认 GUI 不展示。

Bot API `getUpdates` 明确只订阅 `message` 和 `my_chat_member`。群自动检测消费 Telegram 官方 Bot membership 事件，校验 operator、bot identity、chat type、membership status、update offset 和 binding session。`left`/`kicked` 不会成功，旧 update、重复 update、错误 slot、错误用户、不同群和 channel 均被拒绝、忽略或进入冲突状态。

新增 `getChat` 与 `getChatMember` 包装和 group verification API，用于复核群标题、Bot membership、发送能力和 Privacy Mode 提示。三个 slot 的 private user 与 group chat 都一致后才达到 3/3 completed。

`startgroup` 是打开“把 Bot 加入群”界面的官方安全 fallback，不代表 Telegram 会把 payload 作为一条群消息交付，因此真正绑定证据仍来自 `my_chat_member` 或兼容的群命令/update。GUI 不自动创建群。

Telegram Desktop 检测只读取 `tg://` protocol handler 和常见可执行文件提示，并使用 `QDesktopServices.openUrl`。禁止读取 tdata、Session、账号数据库、群列表和聊天历史，也不显示“Telegram 已登录”。

本轮选择性调研只收口 GUI 必需语义：Telegram Bot Deep Linking 的 `start`/`startgroup`、Bot API 的 `my_chat_member`、`getChat`/`getChatMember`，以及 Qt/PyInstaller 的 Windows GUI subsystem 和资源收集方式。实现优先使用官方协议与既有锁定组件，没有引入 MTProto、自研二维码编码器或大型 GUI 框架。

## 7. Hermes、Claude/Codex、cc-connect 与外部边界

Hermes 保持 external-first。已安装且 Owner 为 external 时只读观察或生成非 Secret 计划；未安装时状态为 `pending_component_install`。没有稳定官方 Schema 证据时不猜配置、不写私有数据库、不升级、不重装、不修改 Provider。因此“普通用户已有 Hermes 但尚未配置 Telegram”的自动接线能力仍是已知缺口。

Claude Code 与 Codex 继续通过产品自有锁定 cc-connect、合法 Project Renderer、Windows Credential Manager SecretRef 和受管 lifecycle 接入。GUI 不复制 Agent 安装或 Provider 管理。

Update Lease 仍保证一个 Bot update stream 只有一个 Owner。binding poll 只在显式短时 Operation 内获取 lease；已有 external 或 runtime owner 时不抢占。Webhook 不会被静默删除。

CC Switch 不必安装；检测到时只能作为可选打开入口。产品不读其私有数据库或 Secret，不修改、不 Fork、不自动点击其 GUI。

## 8. Dashboard、刷新、诊断与有限修复

Dashboard 展示整体状态、三个 Agent、六条聊天状态和最近问题，并提供重新配置与 Diagnostics 入口。六条 Link chip 是次级状态，不替代 3/3 binding 或结构化 live 证据。

顶部刷新按钮是全局只读刷新：重新读取 onboarding/dashboard、Agent、Bot identity、binding、group、cc-connect、Hermes 和最近观测状态；刷新期间禁用重复请求并显示轻量旋转。刷新不发送消息、不删除 webhook、不重启 Agent、不重做绑定、不修改系统或 ownership。

Diagnostics 只显示经过脱敏的 code、用户说明和恢复建议。当前有限修复边界是刷新、重试、返回上一步、重新运行快速配置或进入既有计划化操作；没有无确认的通用“一键修复”。

## 9. Secret、QR 与系统安全

Token 只通过 write-only Credential API 进入 Windows Credential Manager。Onboarding/Dashboard Schema 默认不包含 Token、Authorization、binding code、Deep Link、消息正文或 Telegram 登录状态。QR 只含短时 Deep Link，不含 Token；会话过期后服务端拒绝重放。

本轮没有读取或修改系统文件，没有修改 PATH、Task Scheduler、Windows Service、Watchdog、系统 Telegram 数据或 CC Switch 私有数据。构建脚本仅准备 portable per-user candidate；正式运行数据继续位于用户级 LocalAppData。

## 10. Windows GUI 分发

`control-plane/scripts/build_windows_candidate.ps1` 已调整为 candidate `0.2.0-gui`，入口 EXE 为 `AI-Agent-Desktop.exe`。PyInstaller 使用 `--onefile --windowed`，收集 Control Plane、PySide6、qrcode、迁移、GUI assets 和 Windows Credential Manager backend，并附带锁定 cc-connect bundle、依赖锁、验收脚本和用户说明。

构建脚本声明 `black_window=false`、`changes_external_environment=false`、`chrome_agent_required=false`，目标 Windows x64，最低 Windows 10。candidate 已在 Windows 11 x64 构建：EXE 238,392,207 bytes，PE machine `0x8664`、subsystem `2`，`--version` 与 `--headless` smoke 均返回 0；Qt `qwindows.dll`、Control Plane、正式 GUI、qrcode 和 Alembic 资源均被 validator 检出。Windows 10 实机仍保持待验收。

candidate manifest 包含产品、平台、架构、最低系统、cc-connect version/source/SHA、payload 文件大小与 SHA256，以及按排序 payload 计算的 package SHA256。`validate_gui_candidate.py` 会校验 manifest、所有 SHA、必需文件、路径逃逸、敏感模式、EXE `--version`/`--headless` 和 Windows PE GUI subsystem。

candidate 路径为 `control-plane/dist/AI-Agent-Desktop-gui-windows-x64`；EXE SHA256 为 `184e10f805889a66b9923d2601956cd6395ee7120f4b9134e03160f82fc72c7e`，manifest SHA256 为 `8b0bc5fce4935be49ed40a51581169ed278a27ed189b3021da6843e19184559a`，package SHA256 为 `f528f71351acd216b027a3b09cddef1547c88bb5853509737dd003ba038a7ff4`。Windows 10 保持 `PENDING WINDOWS 10 VALIDATION`。

## 11. API、Contract、依赖与迁移

新增只读端点：

- `/api/v1/onboarding/snapshot`
- `/api/v1/dashboard/snapshot`
- `/api/v1/telegram/client-availability`

Telegram binding 响应增加 `private_deep_links` 与 `group_deep_links`，并增加逐 slot group verification。`onboarding.schema.json` 冻结 GUI 读取模型；OpenAPI 与 managed runtime schema 已同步。

新增 GUI 依赖锁 `requirements-gui.in`/`requirements-gui.lock`。qrcode 选择用于成熟二维码生成，Pillow 用于图像资源和兼容输出，PySide6 与 PyInstaller 收集规则显式固定。没有复制外部项目代码；依赖 License 仍应在正式 release notices 中统一复核。

本轮没有为 GUI 新增 Alembic migration；Onboarding read model 从已有 credential、identity、binding、native config、component 状态聚合，避免保存 QR、完整 Deep Link 或 GUI 私有真相。

## 12. 自动化、GUI smoke 与 CI

在仓库本地 `.venv`（含锁定 GUI 依赖）执行：

- `python -m pytest -q`：222 passed、1 skipped、1 warning。
- `python -m pytest tests/test_gui.py tests/test_onboarding_api.py -q`：23 passed、1 warning；candidate validator 回归另有 2 passed。
- `python scripts/validate_contracts.py`：OpenAPI 与四个 JSON Schema 全部通过。
- `mypy control_plane`：98 个 source file 无问题。

本轮使用 `control-plane/.venv` 的 Python 3.12.10 与锁定 GUI 依赖；qrcode 8.2、PySide6 6.7.2、Pillow 11.3.0 均已安装并通过 GUI 测试。未使用真实 Telegram Token。

当前 `ruff check .` 与 `ruff format --check .` 均通过，mypy 与契约验证也通过。`.github/workflows/control-plane-ci.yml` 已加入 Windows GUI lock 安装、离屏 GUI smoke、正式 candidate 构建、candidate validator 和 artifact 上传；GitHub Actions 需在推送后以真实 run 结果回填。

真实 Telegram 在 CI 中继续禁用；Fake tests 覆盖 `/start`、slot、重放、旧 update、wrong user、channel、`my_chat_member`、3/3 同群、getChat/getChatMember 和 lease 边界。GUI smoke 覆盖统一 Shell、真实 QR pixmap、Token 不进入快照、Embedded 真实 snapshot、无 Group QR、一次性 link 刷新保留和图标透明/多尺寸结构。

## 13. 修改范围与事实源

主要新增范围：

- `control-plane/control_plane/gui/`
- `control-plane/control_plane/onboarding/`
- `control-plane/control_plane/api/routers/onboarding.py`
- `control-plane/control_plane/telegram/client_discovery.py`
- `contracts/control-plane-v1/onboarding.schema.json`
- `control-plane/requirements-gui.in`
- `control-plane/requirements-gui.lock`
- `control-plane/scripts/gui_candidate_entry.py`
- `control-plane/scripts/validate_gui_candidate.py`
- `control-plane/tests/test_gui.py`
- `control-plane/tests/test_onboarding_api.py`
- `control-plane/tests/test_gui_candidate_validator.py`

主要修改范围包括 Telegram API/client/binding/identity/model、OpenAPI/managed schema、Windows build script、CI workflow、Control Plane README，以及根目录、product、architecture、security、handoff 和 next-agent 事实源。

受保护内容 `reference-baseline/` 未修改。本轮没有新增 cc-connect Patch、升级锁定 upstream 或改动系统文件；`PUBLIC_FILE_MANIFEST.txt` 与 `SHA256SUMS.txt` 会在最终文件集合确定后重建并复核。

## 14. 已知限制与技术债

- 锁定 cc-connect management API 缺少 bind host 字段，监听范围可能为所有网卡；即使有 Bearer，健康仍只能为 partial。
- 锁定 Telegram Schema 没有 Group Chat ID 白名单，只能限制 operator user；状态为 UNSUPPORTED。
- deep health endpoint 仍为 UNSUPPORTED。
- Hermes 未配置场景缺少稳定官方自动配置 Adapter。
- 新 GUI 尚未完成真实 Telegram、DPI、多显示器、中文长文本、Windows 10 和新 candidate 普通用户现场验收；Windows 11 candidate 的 PE、图标资源、离线 smoke 与 archive 检查已通过。
- 新 GUI 当前以 snapshot/显式刷新和短时 poll 为主，完整 SSE page-active 更新策略仍可继续收口。
- 临时截图和图标生成脚本已从工作区清理，不属于正式 release 文件。

## 15. Git、提交、CI 与回滚

功能实现提交 SHA：`a8849f1710395c934bbdf4b36b9ee04165845c21`。

首次 CI Run ID：`31431495201`。Platform-independent core compatibility 与 Production dependency and import acceptance 成功；Windows-first quality gates 因未安装 `requirements-gui.lock`，在收集 GUI 测试时缺少 Pillow 而失败，后续 cc-connect/candidate 作业因此跳过。

CI 修复提交 SHA：`42b346eade4162510653054bc04b3849356fae99`。修复仅把锁定 GUI 依赖加入 Windows-first quality job 的安装步骤和 pip cache dependency path，不改变产品行为。

功能最终 CI Run ID：`31431933007`。四个作业全部 success，包括正式 GUI candidate 构建、候选校验和两个 Artifact 上传。

报告与公开清单提交 SHA 及其对应 CI Run ID 由 Git 和 GitHub Actions 提交元数据记录，本报告不做自引用。

最终 branch：本地 `main`，远端 `origin/main`；没有创建 PR、功能分支、rebase、force push 或历史重写。

提交前会逐文件审阅并确认工作区只包含本轮变更；回滚时不得使用 `git reset --hard` 或覆盖整棵工作区，应按最终提交边界使用正常 `git revert <commit>`。

## 16. 用户 Live 状态与下一阶段

2026-08-07 的 Hermes、Claude Code、Codex 私聊和群聊六链路可继续记为历史 `LIVE_VERIFIED`。它不能证明本轮新 GUI、Deep Link、QR、`my_chat_member`、结构化 getMe、3/3 binding、correlation 或 Hermes 新流程。

下一阶段准确任务是：

1. 由用户使用新 GUI 完成三 Bot Token、私聊 Start、同群检测和 Step 4 的真实现场验证。
2. 在真实 Windows 10 x64 执行无开发环境验收，保持 Chrome Agent 非必需。
3. 再进入 Installer/Uninstaller、快捷方式、更新/回滚、Release assets 和有证书时的代码签名；MSI 与签名在完成前继续标记 DEFERRED。

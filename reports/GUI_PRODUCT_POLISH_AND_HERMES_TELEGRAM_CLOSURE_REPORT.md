# GUI Product Polish、Hermes Telegram Native Onboarding 与 Pre-Beta 收口报告

更新时间：2026-08-15

## 1. 结论

本阶段从 `1506f8d997b1339665462f87d76aa3476bb97acf` 开始，完成 `0.4.0-prebeta` Windows x64 Candidate 所需的 GUI 产品级精修、Hermes Native Telegram 最小配置闭环、契约扩展、质量门禁和文档收口。核心业务范围冻结为 Windows 10/11、Telegram、Hermes/Claude Code/Codex 与产品自有 cc-connect；不新增 Agent/Channel，不安装或升级 Hermes，不管理 Provider/Model/Tool/Hermes Studio。

整体证据等级仍为 `PARTIAL`：Windows 11 本地 Candidate 为 `LOCAL_VERIFIED`；新 GUI Telegram、Hermes Native Telegram Setup 为 `PENDING USER LIVE VALIDATION`；Windows 10 为 `PENDING WINDOWS 10 VALIDATION`；Installer/MSI/signing 为 `DEFERRED`。2026-08-07 旧入口六链路仍保留历史 `LIVE_VERIFIED`，不被本轮自动化改写。

## 2. GUI 产品精修

图标系统：新增项目内 `IconRegistry`、SVG Renderer 和本地 SVG 资产子集，覆盖 refresh、window controls、eye/eye-off、QR、Telegram action、Agent、status、info、warning、error、group、copy、shield、arrow 等用户可见控件。资产由项目自写，未 vendoring 第三方图标库；upstream SHA 为 `N/A`，许可证为项目 `Apache-2.0`，不需要额外第三方 attribution。原有 App Icon 保持不变。

TitleBar：Refresh 与窗口控制分组，Minimize/Maximize/Restore/Close 使用统一 hit target、SVG 尺寸和状态样式；最大化时切换 Restore 图标，Close hover 使用克制的浅红。Frameless 基础拖拽、双击最大化/恢复、最小化、最大化、恢复、关闭和 resize 路径保留；Windows Snap 的 undocumented hack 未引入。

视觉与交互：新增统一 Design Tokens（颜色、字体层级、间距、圆角、控件高度、图标尺寸、阴影），提升 Glass Card 白蓝分离度、border 和 soft shadow；Token 页使用 eye/eye-off，默认 masked，失焦恢复隐藏；Private 页使用 Telegram/QR 正式图标，Group 页不显示 QR、不枚举群；Completion 页保留可读行高，不用 9px/10px 压缩布局；Live Confirm、Config Help、Hermes Existing Bot Conflict 和 QR 使用统一 GlassDialog；Toast 统一 info/success/warning/error 语义。

Forbidden Glyph 质量门禁扫描正式 GUI 用户可见控件，禁止以 `🚀 ★ ◇ ▤ ➤ ▦ ⌁ ϟ ● ✓ ↻ — □ ❐ × ‹ › ⓘ 👥` 等字符充当图标。测试允许中文和文档历史讨论，不做错误的全 Unicode 禁止。

## 3. Hermes 官方能力与边界

官方事实源：`https://github.com/NousResearch/hermes-agent.git`，本阶段重新读取官方 `main` 为 `7a16840addc345666abc510dbfc2ffbe6631f948`；本机 Hermes `0.19.0`。公开能力包括 `hermes config env-path`、`hermes gateway setup/status/start/stop/restart` 和公开 `.env` Telegram 配置面。Provider、Model、Tool、Hermes Studio、安装、升级和通用配置管理仍由 Hermes/外部工具负责。

CLI Capability Probe：使用 argv 数组、`shell=False`、stdin 关闭、bounded stdout/stderr、timeout、Windows `CREATE_NO_WINDOW`；Token 不允许进入 subprocess argv。只探测 `--version`、`config env-path` 和 Gateway help/status，不在健康检查中启动、停止或发送 Telegram 消息。

HermesTelegramConfigurationAdapter：

- `UNCONFIGURED`：使用绑定阶段的当前 Bot Token，生成显式 plan/apply。
- `SAME_BOT`：保留现有 Bot，可选择复用；不静默覆盖。
- `DIFFERENT_BOT`：形成冲突，用户必须选择复用既有 Bot 或切换当前 Bot。
- `INVALID_TOKEN`、`PARTIAL`、`UNKNOWN`：阻断或要求修复，不猜测成功。
- `.env` 事务只拥有 `TELEGRAM_BOT_TOKEN` 与 `TELEGRAM_ALLOWED_USERS`；未知键、注释、重复键归一、编码、权限、符号链接和原子替换均有保护。
- 回滚材料仅在内存中保留，不生成明文 `.bak`；写入使用临时文件、flush/fsync、replace 和目录 fsync。
- 默认只合并绑定的 `TELEGRAM_ALLOWED_USERS` operator ID；不写 `TELEGRAM_GROUP_ALLOWED_CHATS`，不设置 Allow-All，不修改 `TELEGRAM_HOME_CHANNEL`。原因是 group-wide scope 更宽，且上游当前没有可靠的 Group Chat ID 白名单契约。
- 配置前后通过 Telegram Update Lease 防止与 Hermes/cc-connect runtime 竞争；Gateway 如需临时停止，失败时恢复原状态，成功后按原状态执行 start/restart。

## 4. API 与 GUI 接线

OpenAPI 和 managed-runtime schema 新增 Hermes Telegram readiness、change plan、apply、conflict、Gateway status 与诊断语义。响应不包含 Token、raw env、Provider secret、私聊/群消息正文或完整私有路径。Step 4、Dashboard、Diagnostics 和统一刷新均展示 Hermes readiness，但 `Binding != Chat Health`，Gateway running 也不等于真实聊天 `LIVE_VERIFIED`。

## 5. Candidate 与依赖

Candidate 目录：`control-plane/dist/AI-Agent-Desktop-0.4.0-prebeta-windows-x64`

- `AI-Agent-Desktop.exe`：69,299,058 bytes；SHA256 `dbebb193cd1ec3779f1dab796f3b075c061f906bfd4b8270e055bf790c7b8910`
- `candidate-manifest.json`：SHA256 `f85874a6f0308459660e1e13f688bf46a7455f56a93e840bd70936b2121714c1`
- Candidate package：约 96,330,897 bytes（91.87 MiB）；SHA256 `72f93cdf3ad38db8b41f818dc717826d1939404260e65af9e5d2022c0e60e92f`
- cc-connect：`v1.4.1-patchset0.1-fc315d2`，source commit `fc315d213b49d62e9d90ea4a510189d4115e636f`，SHA256 `cd1b0787709c0401a42f7c3ce5321184889adbfbf3b080190fee180afc977eec`

Candidate validator、`--version`、`--headless`、PyInstaller SVG/Hermes module bundling和离线 Windows wrapper 均通过。当前机器是 Windows 11，Windows 10 wrapper 正确返回 `NOT_WINDOWS_10_X64`。

## 6. 质量门禁

- pytest：`264 passed, 2 skipped, 1 warning`
- Ruff check：通过
- Ruff format check：158 files already formatted
- `mypy control_plane`：通过，112 source files
- OpenAPI/JSON Schema contract validation：通过
- GUI candidate validator：通过
- Windows offline candidate smoke：通过
- `git diff --check`：通过
- 敏感信息扫描：仓库文本、报告、日志与候选包均未发现真实 Telegram Token、Bot Token、Binding code 或 API key；测试 synthetic token 仅用于隔离测试，不作为泄漏。

本报告不宣称 `mypy control_plane scripts` 全量通过；scripts 目录存在 3 个既有类型错误，当前 CI 只执行 `mypy control_plane`。

## 7. 用户验收状态与后续

Windows 11：`LOCAL_VERIFIED`。

Windows 10 x64：`PENDING WINDOWS 10 VALIDATION`。

新 GUI Telegram 私聊/同群：`PENDING USER LIVE VALIDATION`。

Hermes Native Telegram Setup：`PENDING USER LIVE VALIDATION`。

2026-08-07 旧入口六链路：`LIVE_VERIFIED`（历史证据，不覆盖新 GUI）。

Installer/MSI、卸载器、快捷方式、GitHub Release Asset、签名和 SmartScreen：`DEFERRED`。

推送后回填：本轮 GitHub Actions Run ID、GUI artifact ID/digest、cc-connect artifact ID/digest，以及最终 main SHA。下一阶段只做用户 Win11 GUI/Hermes live、Windows 10 实机、Installer/Release/签名，不继续扩展核心业务范围。

回滚策略：候选包不写入系统环境；Hermes `.env` 事务使用内存 receipt 回滚，Gateway 恢复原状态；cc-connect 使用产品自有 revision/backup/rollback；代码回滚使用 main 上的正常反向提交，禁止 reset/rebase/force push。

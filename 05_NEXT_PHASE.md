05 下一阶段
============

更新时间：2026-08-11

一、当前切片
------------

本阶段名称仍为“最小 GUI、十分钟 Onboarding 与 Windows 自包含分发切片”。核心实现和可验证的 portable Windows candidate 已完成，但真实 Telegram GUI 验收、Windows 10、安装器和签名尚未完成。

已实现：

PySide6 6.7.2 + Qt Widgets + QSS GUI，版本入口 `0.2.0-gui`；统一标题栏、欢迎页、固定四步 Wizard Shell、Token 输入、私聊 deep link/QR、群 deep link/检测、完成页、Dashboard、Diagnostics 和刷新/恢复操作。

本地 Control Plane onboarding API：`/api/v1/onboarding/snapshot`、`/api/v1/dashboard/snapshot`、`/api/v1/telegram/client-availability`，以及现有 Telegram credential、getMe、binding、poll API 的 GUI 客户端调用。

Windows candidate 脚本已切换到 `AI-Agent-Desktop.exe`、候选版本 `0.2.0-gui`、`--windowed`、PySide6/qrcode/Pillow 锁和图标资源，并提供本地 `validate_gui_candidate.py` 设计好的 manifest、SHA256、无控制台、Qt 资源和 Secret 扫描门禁。

二、证据等级
------------

当前工作区全量 pytest 为 222 passed、1 skipped、1 warning；GUI/onboarding 定向测试为 23 passed，candidate validator 回归另有 2 passed。该结果是本地自动化/合成证据，不是 Telegram 实时验收。

历史 2026-08-07 的直接 Telegram 六链路确认仍可记录为旧入口的 `LIVE_VERIFIED`，但它没有经过本轮新 GUI；新 GUI 私聊激活和群自动检测固定为 `PENDING USER LIVE VALIDATION`。不得伪报 Hermes 新 GUI 或真实消息已验证。

Windows 11 已完成 `0.2.0-gui` candidate 构建、manifest/SHA256、PE GUI subsystem、离线 smoke、Qt/内嵌模块和敏感信息门禁。Windows 10 x64 为 `PENDING WINDOWS 10 VALIDATION`。

三、明确延期
------------

MSI、正式安装器/卸载器、Start Menu/桌面快捷方式发布体验、代码签名、证书与 SmartScreen 分发策略均为 `DEFERRED`。旧 `control-plane/dist/AI-Agent-Desktop-stage-a-*` 只代表历史 Tk 验收向导，不能作为 `0.2.0-gui` candidate。

四、下一步门禁
--------------

下一步由用户在真实 Telegram 完整走私聊和同群检测，再在 Windows 10 x64 普通用户环境重复验收。候选图标透明 alpha、黑底边缘、`--version`、`--headless`、PE GUI subsystem、Qt platform/resource、manifest/SHA256 和 Secret 扫描已在 Windows 11 通过。

若要生成机器可审计的 Telegram live 证据，必须用户显式开始新的三 Bot getMe、3/3 私聊/同群绑定和 correlation 流程；Fake 结果、Demo 模式或旧用户口头确认都不能替代。

五、边界与禁止项
----------------

继续保持 Windows 10/11、Telegram、Hermes/Claude Code/Codex、cc-connect 和唯一 ManagementOwner；不新增 Agent/Channel，不升级 cc-connect 或增加 Patch，不安装/升级/接管 Hermes，不读取 Telegram 用户登录状态、tdata、群列表或聊天正文，不发送默认真实测试消息，不修改 PATH、计划任务、Watchdog、注册表或 Reference Baseline。最终公开文件集合确定后重建 `PUBLIC_FILE_MANIFEST.txt` 与 `SHA256SUMS.txt`。

六、交付状态
------------

整体：`PARTIAL`。

新 GUI 私聊/群自动检测：`PENDING USER LIVE VALIDATION`。

Windows 10 x64：`PENDING WINDOWS 10 VALIDATION`。

MSI/签名：`DEFERRED`。

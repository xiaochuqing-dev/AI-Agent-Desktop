05 下一阶段
============

更新时间：2026-08-13

一、当前切片
------------

GUI Pre-Beta 的 Agent Detection、Runtime Readiness、Live E2E 接线和状态语义已完成。当前只剩用户真实 Telegram GUI 验收、Windows 10 实机、Installer/Release 准备和签名。

已实现：

PySide6 6.7.2 + Qt Widgets + QSS GUI，版本入口 `0.3.0-prebeta`；固定四步流程已接入真实 Agent Detection、严格 cc-connect Runtime Readiness、Binding/Chat Health 分离、用户确认 Live E2E、Dashboard 和 Diagnostics。

本地 Control Plane onboarding API：`/api/v1/onboarding/snapshot`、`/api/v1/dashboard/snapshot`、`/api/v1/telegram/client-availability`，以及现有 Telegram credential、getMe、binding、poll API 的 GUI 客户端调用。

最终 candidate 为 `control-plane/dist/AI-Agent-Desktop-0.3.0-prebeta-windows-x64-final3-20260813`。EXE SHA256 `7b2a2370f17eb0d1ff181d8fbf6fa36a221672a3bc9525f4c3fca74aa2186223`，manifest SHA256 `be11edaed961795bf6ce8383724775353106e8b0bbbde4288bd5ab234b59757a`，package SHA256 `1ee0e0390cd254066cfd3897a6e8a6ca58ed9a8cdeac6ac7780f6c9c92d7613c`，66.05 MiB。

二、证据等级
------------

当前工作区全量 pytest 为 240 passed、1 skipped；Ruff、format、mypy 104 files 和全部 OpenAPI/JSON Schema 验证通过。该结果是本地自动化/合成证据，不是 Telegram 实时验收。

历史 2026-08-07 的直接 Telegram 六链路确认仍可记录为旧入口的 `LIVE_VERIFIED`，但它没有经过本轮新 GUI；新 GUI 私聊激活和群自动检测固定为 `PENDING USER LIVE VALIDATION`。不得伪报 Hermes 新 GUI 或真实消息已验证。

Windows 11 已完成 `0.3.0-prebeta` candidate 构建、manifest/SHA256、PE GUI subsystem、离线 ordinary-user smoke、Qt/内嵌模块和敏感信息门禁。Step 4/Dashboard 已做原生 Qt 1280×720 视觉复核。Windows 10 x64 为 `PENDING WINDOWS 10 VALIDATION`。

三、明确延期
------------

MSI、正式安装器/卸载器、Start Menu/桌面快捷方式发布体验、代码签名、证书与 SmartScreen 分发策略均为 `DEFERRED`。旧 `stage-a`、`0.2.0-gui` 和本轮临时 final/final2 目录均不是最终 `0.3.0-prebeta` candidate。

四、下一步门禁
--------------

下一步由用户用 final3 candidate 完整走三个 Token、三私聊 Start、三 Bot 同群、Agent Detection、Runtime 和可选六链路 Live E2E，再在 Windows 10 x64 普通用户环境重复验收。通过后修复现场问题，然后进入 Installer、卸载、快捷方式、Release Asset 和签名准备。

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

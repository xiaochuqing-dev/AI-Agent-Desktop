05 下一阶段
============

更新时间：2026-08-30

一、当前切片
------------

GUI Product Polish、Agent Detection、Runtime Readiness、Live E2E 接线、Hermes Telegram Native Onboarding 与产品受管 cc-connect v1.5.0 Stable 融合升级已完成。当前只剩用户真实 GUI/Hermes Telegram 验收、Windows 10 实机、Installer/Release 准备和签名。

已实现：

PySide6 6.7.2 + Qt Widgets + QSS GUI，版本入口 `0.4.1-prebeta`；固定四步流程已接入本地 SVG IconRegistry、统一 Design Tokens/TitleBar/GlassDialog、真实 Agent Detection、严格 cc-connect Runtime Readiness、Binding/Chat Health 分离、Hermes Telegram Native Configuration、用户确认 Live E2E、Dashboard 和 Diagnostics。

本地 Control Plane onboarding API：`/api/v1/onboarding/snapshot`、`/api/v1/dashboard/snapshot`、`/api/v1/telegram/client-availability`，以及现有 Telegram credential、getMe、binding、poll API 的 GUI 客户端调用。

最终 candidate 为 `control-plane/dist/AI-Agent-Desktop-0.4.1-prebeta-windows-x64`。EXE SHA256 `dfe9ad2bfef7f9a7afe402753a2cc5c1eacaf7bb2b26c047067ae97b5630d99e`，manifest SHA256 `10a148e3ac827476b034d6549f258c98034af80b81e96c71e80e23ceb4ef18dd`，package SHA256 `70c6827007e418348b4a52e89344113abcf2e75ed5306fa5e077b09604df41ea`，总包约 117.58 MiB。

二、证据等级
------------

当前工作区全量 pytest 为 269 passed、2 skipped；Ruff、format、`mypy control_plane`（112 files）和全部 OpenAPI/JSON Schema 验证通过。cc-connect 定向 Go test/vet/build、真实配置 Loader、Patch 有效性变异测试、双 PowerShell 可复现构建与候选包校验也通过。该结果是本地自动化/合成证据，不是 Telegram 实时验收；`scripts/` 的额外 mypy 不计入 CI 门禁。

历史 2026-08-07 的直接 Telegram 六链路确认仍可记录为旧入口的 `LIVE_VERIFIED`，但它没有经过本轮新 GUI；新 GUI 私聊激活和群自动检测固定为 `PENDING USER LIVE VALIDATION`。不得伪报 Hermes 新 GUI 或真实消息已验证。

Windows 11 已完成 `0.4.1-prebeta` candidate 构建、manifest/SHA256、PE GUI subsystem、离线 ordinary-user smoke、Qt/内嵌模块和敏感信息门禁。Step 4/Dashboard 已做原生 Qt 1280×720 视觉复核；当前机器为 Windows 11，状态 `LOCAL_VERIFIED`。Windows 10 x64 为 `PENDING WINDOWS 10 VALIDATION`。

三、明确延期
------------

MSI、正式安装器/卸载器、Start Menu/桌面快捷方式发布体验、代码签名、证书与 SmartScreen 分发策略均为 `DEFERRED`。旧 `stage-a`、`0.2.0-gui`、`0.4.0-prebeta` 和旧 final/final2/final3 目录均不是最终 `0.4.1-prebeta` candidate。

四、下一步门禁
--------------

下一步由用户用 `0.4.1-prebeta` candidate 完整走三个 Token、三私聊 Start、三 Bot 同群、Agent Detection、Runtime、Hermes Native Telegram 分支和可选六链路 Live E2E，再在 Windows 10 x64 普通用户环境重复验收。通过后修复现场问题，然后进入 Installer、卸载、快捷方式、Release Asset 和签名准备。

若要生成机器可审计的 Telegram live 证据，必须用户显式开始新的三 Bot getMe、3/3 私聊/同群绑定和 correlation 流程；Fake 结果、Demo 模式或旧用户口头确认都不能替代。

五、边界与禁止项
----------------

继续保持 Windows 10/11、Telegram、Hermes/Claude Code/Codex、cc-connect 和唯一 ManagementOwner；不新增 Agent/Channel，不继续升级 cc-connect 或增加 Patch，不安装/升级 Hermes。已安装但 Telegram 未配置的 Hermes 仅可通过官方公开 `.env` 与 Gateway CLI 完成最小 Telegram 接入；已有配置不静默覆盖，Provider/Model/Tool 仍由 Hermes/外部工具管理。不读取 Telegram 用户登录状态、tdata、群列表或聊天正文，不发送默认真实测试消息，不修改 PATH、计划任务、Watchdog、注册表或 Reference Baseline。最终公开文件集合确定后重建 `PUBLIC_FILE_MANIFEST.txt` 与 `SHA256SUMS.txt`。

六、交付状态
------------

整体：`PARTIAL`。

新 GUI 私聊/群自动检测：`PENDING USER LIVE VALIDATION`。

Windows 10 x64：`PENDING WINDOWS 10 VALIDATION`。

MSI/签名：`DEFERRED`。

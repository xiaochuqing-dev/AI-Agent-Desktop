# GUI Pre-Beta Agent Detection、Runtime 与 Live 闭环报告

更新时间：2026-08-13

## Executive Summary

本轮从 `df345946ce2e0526ed2f57a32ba3182a6918f053` 开始，在不升级 cc-connect、不增加 Patch、不修改 Reference Baseline、不扩展 Agent/Channel 的前提下，完成 `0.3.0-prebeta` GUI Pre-Beta 收口。真实 Agent Detection、严格 cc-connect Runtime Readiness、Telegram Binding 与 Chat Live Health 分离、Live E2E GUI、Dashboard、Diagnostics、全局刷新和 1280×720 原生布局均已落地。

本地证据为 240 passed、1 skipped；Ruff、format、mypy 104 files、OpenAPI/JSON Schema 和最终 candidate validator 均通过。本机 Agent 检测为 Hermes 0.19.0、Claude Code 2.1.228、Codex 0.147.0，均 healthy。新 GUI Telegram 仍为 `PENDING USER LIVE VALIDATION`，Windows 10 为 `PENDING WINDOWS 10 VALIDATION`。2026-08-07 六条真实链路只保留为旧入口 `LIVE_VERIFIED`。

## 范围与 Git

- Start SHA：`df345946ce2e0526ed2f57a32ba3182a6918f053`
- End feature SHA：最终提交后由 Git 记录；报告不制造自引用 SHA
- 主线：main only
- 分支/PR：未创建
- Reference Baseline、`src/`、5 个 cc-connect Patch：未修改
- cc-connect：继续固定 `fc315d213b49d62e9d90ea4a510189d4115e636f`、patchset 0.1
- 产品范围：Windows 10/11、Telegram、Hermes/Claude Code/Codex、cc-connect；未新增 Agent 或 Channel

## 本阶段 P0

1. Agent installed/healthy 不再由 Telegram Bot Identity 伪装。
2. Step 4 不再把配置写入等同为 cc-connect 正在运行。
3. Binding 完成不再等同聊天可用或 LIVE_VERIFIED。
4. 既有 LiveE2ETestService 已通过 GUI 用户确认流程接入。

## Agent Detection 架构

实现位于 `control-plane/control_plane/agent_detection/`。共享层提供 Windows executable discovery、安全版本探测、输出限制、超时和结果模型；Hermes、Claude Code、Codex 使用独立 detector，避免万能规则吞掉各自安装来源和输出差异。

统一结果包含 slot、display name、installed、version、status、probe status、detection source、observed time、diagnostic code 和内部 executable path。公开 GUI/API 默认不泄露完整路径。

Discovery 按 PATH 目录顺序解析，而不是按扩展名全局优先；这修复了后置 WindowsApps `codex.exe` 抢在前置 npm `codex.cmd` 前导致 launch_error 的问题。Known locations 和 wrapper 仅作为受控 fallback，不接受用户选择任意文件。

## 三个 Detector

Hermes、Claude Code、Codex 均使用官方安全版本入口 `--version`。探测采用 argv list、shell=False、no stdin、短 timeout、Windows CREATE_NO_WINDOW、Unicode 安全与受限 stdout/stderr。环境保留执行所需的安全系统项，同时移除 Token/API Key/Authorization 类变量。

本机 `LOCAL_VERIFIED`：

- Hermes：0.19.0，healthy
- Claude Code：2.1.228，healthy
- Codex：0.147.0，healthy

版本解析兼容 semver/build string；无法解析版本时保持 installed=true、version unknown/partial，不误报 not found。Detector 不写死当前版本，不读取 Agent 登录状态、账号、订阅、配额、Provider、模型或 Secret。

## CC Switch 调研与边界

- Upstream：farion1231/cc-switch
- 参考 SHA：`1f38c83826a8bca3c1a7a18d9629f05a914718fd`
- License：MIT
- 参考位置：`src-tauri/src/commands/misc.rs`
- 复用方式：behavioral/reference implementation inspired by CC Switch
- 直接复制第三方代码：否
- 新增第三方 License/Notice：不需要

参考内容限于 Windows executable lookup、PATH/known-location、wrapper、version probe、timeout、encoding、normalization 和 fallback 策略。产品不调用 CC Switch 作为 Detector 后端，不读取其 SQLite、Provider、配置或 Secret；CC Switch 继续为可选打开/获取入口，未安装不阻塞核心流程。

## Onboarding、Dashboard 与 Diagnostics

OnboardingSnapshot 和 DashboardSnapshot 已包含真实 Agent 读模型。全局刷新会触发受控 detector refresh，不在每次 repaint 执行 subprocess。Diagnostics 新增 Agent not found、version unknown、probe timeout/failed、Runtime not ready、Chat not live/stale 等稳定诊断语义。

connected 语义已修正：Claude/Codex 只有 detector acceptable 且严格 Runtime Ready 才为 true；Hermes 是 external runtime，保持 null。Bot getMe 只证明 Telegram Identity，不决定 Agent connected。

## Step 4 与 Runtime Readiness

Step 4 保留固定结构，但检查项改用真实语义：Telegram、Agent、Runtime、配置、Chat Health。完成配置路径会确保锁定 cc-connect 已安装、Owner 正确、原生配置有效，并根据现场执行 start/reconcile。

只有下列证据同时满足才标记 Runtime Ready：

- 正确 PID 和持久化 identity
- 正确 executable/artifact SHA
- configuration revision 一致
- 目标端口由该 PID 拥有
- startup stability window 通过
- 未检测到 fatal log

配置已写但 stopped、端口冲突、PID stale、wrong exe、revision drift、startup timeout 或短时崩溃均不得完成 Onboarding。Hermes 不由该受管路径启动或接管。

## Binding、Live 与 Evidence Revision

Telegram Binding 和 Chat Live Health 已分离。状态覆盖未绑定、已绑定、ready_for_test、live_verified、failed、stale/需重新确认。配置或凭据 revision 变化会使旧 live 证据失效，不再把历史成功永久显示为当前成功。

GUI “快速验证聊天”会先显示明确确认：向三个 Bot 私聊和群聊分别发送一条短测试消息，共六条。每条链路最多一条、无自动重试；取消不会发送，用户也可选择以后再验证。运行结果继续使用既有 immutable plan、confirmation、correlation 和 failure evidence，不保存消息正文。

证据等级：

- 新 GUI Telegram：`PENDING USER LIVE VALIDATION`
- 2026-08-07 旧入口六链路：`LIVE_VERIFIED`
- 自动化 Live E2E/Fake/Demo：`SYNTHETIC_VERIFIED`，不能升级用户证据

## GUI Polish

Step 4 在原生 Windows Qt 1280×720 截图中曾出现检查行和 Agent 行文字重叠。最终将检查项固定为紧凑可读行、Agent 改为横向三列状态、收紧结果卡和 HelpRail，并增加关键按钮边界、检查行不重叠、三 Agent 同行回归测试。

原生 Windows Qt 复核结论：Step 4、Dashboard 无文字重叠，关键按钮未越界。该结论是 Windows 11 本机视觉证据，Windows 10 和更多 DPI 仍由下一阶段现场验证。

## Candidate

- Version：`0.3.0-prebeta`
- Path：`control-plane/dist/AI-Agent-Desktop-0.3.0-prebeta-windows-x64-final3-20260813`
- EXE SHA256：`7b2a2370f17eb0d1ff181d8fbf6fa36a221672a3bc9525f4c3fca74aa2186223`
- Manifest SHA256：`be11edaed961795bf6ce8383724775353106e8b0bbbde4288bd5ab234b59757a`
- Package SHA256：`1ee0e0390cd254066cfd3897a6e8a6ca58ed9a8cdeac6ac7780f6c9c92d7613c`
- cc-connect SHA256：`cd1b0787709c0401a42f7c3ce5321184889adbfbf3b080190fee180afc977eec`
- EXE size：69,258,306 bytes，66.05 MiB
- PyInstaller：6.21.0，Python 3.12.10，PySide6 6.7.2，onefile/windowed
- Validator：passed
- `--version` / `--headless`：passed
- Windows 11 x64 ordinary-user smoke：passed
- Real Telegram access during validation：false
- Windows 10：`PENDING WINDOWS 10 VALIDATION`

PyInstaller 已移除过度 `collect-all`，只收集 Control Plane 数据与必要 hidden imports。EXE 从约 225 MiB 降至 66.05 MiB，冷启动恢复正常。candidate validator 和 Windows wrapper 会在 timeout 时清理 onefile 进程树，避免残留。

## 测试与 CI

本地最终结果：

- pytest：240 passed、1 skipped
- Ruff lint：passed
- Ruff format：156 files formatted/check passed
- mypy：104 source files passed
- OpenAPI/JSON Schema：全部 passed
- candidate validator：passed
- Windows wrapper smoke：passed

最终 GitHub Actions Run ID：提交并推送后回填到 GitHub Actions 事实记录；不得在运行前虚构。本轮 CI Artifact 名为 `ai-agent-desktop-0.3.0-prebeta-windows-x64`。

## 安全与无副作用

Agent subprocess 不读 Secret、不执行不可信参数、不修改 PATH/注册表/计划任务/Watchdog。真实 Telegram 在自动化和 candidate smoke 中被禁用，消息发送数为 0。未升级 cc-connect、未增加 Patch、未修改 Reference Baseline、未接管 Hermes 或 CC Switch。

## 已知缺口与下一阶段

- 新 GUI 三私聊、三同群和可选六链路：`PENDING USER LIVE VALIDATION`
- Windows 10 x64 ordinary-user candidate：`PENDING WINDOWS 10 VALIDATION`
- Hermes 未配置/外部 Owner 的完整产品化处理：PARTIAL
- 独立 Control Plane 更大重构：DEFERRED
- MSI/Installer/Uninstaller/Start Menu/Desktop shortcut：DEFERRED
- Signing/SmartScreen：DEFERRED

下一阶段精确顺序：用户用 final3 candidate 完成真实 GUI live 验收，修复现场问题；Windows 10 实机验收，修复现场问题；再做 Installer、卸载、快捷方式、GitHub Release Asset、更新/回滚和有证书时的签名，最后进入小范围 Beta。

## Rollback

GUI/API/Detector 改动可由正常 Git revert 回退；未修改外部 Agent 安装、Reference Baseline 或 cc-connect patchset。candidate 是 portable 目录，可直接停止使用并删除；产品自有 cc-connect 仍使用既有安装/配置备份/回滚和所有权保护机制。

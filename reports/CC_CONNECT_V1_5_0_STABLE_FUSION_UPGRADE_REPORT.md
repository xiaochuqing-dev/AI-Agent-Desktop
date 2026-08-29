# cc-connect v1.5.0 Stable 融合升级、Patch 收敛与回归闭环报告

更新时间：2026-08-30

## 一、结论

本轮已按实际仓库源码完成产品受管 cc-connect 从 v1.4.1 到 Stable v1.5.0 的融合升级。上游源码、Patch、构建输入、原生配置 Renderer、安装锁、升级与回滚状态、机器契约、GUI 候选包和 GitHub Actions 均已形成可复核闭环。

源码与自动化交付状态为 COMPLETE。产品发布状态仍为 PARTIAL，因为新 GUI 的真实 Telegram 用户验收、物理 Windows 10 x64 普通用户实机验收、正式安装器/卸载/签名尚未完成。本轮没有访问真实 Telegram，也没有发送真实消息。

## 二、范围与提交

- 实施起点：`74c81d077d4f4e7dc72937af5bd9253eb261d670`
- 功能提交：`aca96a0a456fa60a0c00fce4452b771e4e6043f0`
- 功能闭环提交：`725d371bf2f662fc456fdf4d5df80900f4821624`
- 上游仓库：`https://github.com/chenhg5/cc-connect.git`
- 上游版本：`v1.5.0`
- 精确源码：`17c61062c2f9ce9bcdd45a2082e491f9743a2770`
- 旧源码：`fc315d213b49d62e9d90ea4a510189d4115e636f`
- 上游差异：47 commits、80 files、8227 insertions、777 deletions
- 上游提交时间：`2026-08-16T15:04:20Z`

上游发布说明没有声明破坏性变更，并明确 v1.4.1 配置可以继续使用；仓库仍以真实 v1.5.0 Loader 进行兼容性验证，而不是只依赖发布说明。

## 三、Patch 收敛结果

Patchset 从 0.1 收敛为 `0.2`，001–004 在 v1.5.0 精确源码上重放，005 因上游已经吸收对应清理而退役。

1. `001-telegram-directed-routing.patch`
   SHA256：`675437ee433a1f9cca6e43b8e3f7b77e012098cbff0bbfdf65a19d12bed89b37`
   显式 @mention 优先于 reply 路由，并覆盖 text 与 caption。

2. `002-hook-config-headers.patch`
   SHA256：`136edd956a33bca4225841a6473b512e05e109edcf09d350e8c54d9c6c3be246`
   自定义 Hook Headers 从 config 贯通 main 与 core；深复制隔离调用方修改，协议控制 Header 最后写入，避免被配置覆盖。

3. `003-relay-response-prefix.patch`
   SHA256：`f1d1e6dc7a553b889e9a6d04c4215bc1de5a920310f1c3602c18d0a56e5ed2b8`
   Relay 请求语义不变，仅响应不再附加 `[toName]` 前缀。

4. `004-message-delivery-hooks.patch`
   SHA256：`5302466a7d65c09cc61aa8686d113ff5e9a6b6bb98040ba49d553924cf72b101`
   改为每次成功投递即时上报真实 Message ID，不再依赖共享 `lastSentMessageID`。文本分片、fallback、媒体、按钮、预览、并发和 panic 路径均有测试。

每个活动 Patch 都有语义有效性/变异门禁，可证明删除关键补丁语义会导致对应测试失败。Patch 005 不再进入锁文件和构建链。

## 四、锁定制品与可复现构建

- Artifact ID：`cc-connect-v1.5.0-patchset0.2-17c6106-windows-amd64`
- Version：`v1.5.0-patchset0.2-17c6106`
- Toolchain：Go 1.26.5、windows/amd64、CGO=0
- Build tags：`no_web`、`goolm`、`no_pi`
- SOURCE_DATE_EPOCH：`1786892660`
- EXE 大小：54266368 bytes
- EXE SHA256：`67a127b6c59b942058ed2bd8c6237ff613e37eb3df64e7cd6ea0c18f3c418144`
- Bundle manifest SHA256：`0550d3a8c5892949be68c0f932ea8a21206f58ff0b87bd1390f821957bfc770e`
- Artifact lock SHA256：`065832354b68c8556d9bcc97a791505da8b7b3b11d3656bd3234d048f0096e7b`
- 签名状态：unsigned

Integration 与 Control Plane 两份 artifact-lock 字节级一致。Windows PowerShell 5.1 与 PowerShell 7 验证通过；相同输入连续构建两次得到同一 EXE SHA256。

## 五、配置、升级与回滚

Renderer 证据升级为 `cc-connect-17c6106-native-v2`。机器契约只允许 Renderer 与源码证据成对出现：新 v2/17c6106 用于当前运行，旧 v1/fc315d2 仅保留为回滚兼容；新旧错配会被 Schema 和 Python Model 同时拒绝。

Legacy 与当前原生 TOML fixture 均由真实 v1.5.0 配置 Loader 读取。Windows checkout 的 fixture 强制 LF，避免 Git 自动换行改变字节比较结果。

受管升级执行停止旧运行体、写入新 revision、校验精确 EXE/config/source/renderer/port/PID readiness 后才提交成功；失败路径恢复旧二进制、配置、revision、状态和所有权。安装、升级、严格运行证据、端口冲突、外部 owner 保护、失败回滚和重启 reconcile 均有自动化覆盖。

## 六、GUI 候选包

候选目录：`control-plane/dist/AI-Agent-Desktop-0.4.1-prebeta-windows-x64`

- 文件数：16
- 目录总大小：123287099 bytes
- `AI-Agent-Desktop.exe` 大小：68912687 bytes
- EXE SHA256：`dfe9ad2bfef7f9a7afe402753a2cc5c1eacaf7bb2b26c047067ae97b5630d99e`
- Candidate manifest SHA256：`10a148e3ac827476b034d6549f258c98034af80b81e96c71e80e23ceb4ef18dd`
- Package SHA256：`70c6827007e418348b4a52e89344113abcf2e75ed5306fa5e077b09604df41ea`

候选验证器、普通用户 version/headless smoke、离线包结构和 archive 校验通过。当前验证主机为 Windows 11，因此 Windows 10 wrapper 正确报告非 Windows 10；这不能替代物理 Windows 10 x64 实机验收。

## 七、本地与运行验收

- Pytest：269 passed、2 skipped
- Ruff lint 与 format：通过
- Mypy：112 files，0 issues
- OpenAPI/JSON Schema：5 项全部通过
- 定向契约与原生配置测试：19 passed
- Go 定向测试、fmt、vet、build、Patch 有效性、真实 Loader 兼容与双构建复现：通过
- Windows Credential Manager：随机 synthetic reference 写入、替换、读取与清理通过
- 隔离安装、配置、产品 owner、端口冲突、停止/重启/reconcile、Bearer management probe：通过

上游在无真实 Secret 时不支持持续在线模式，因此 managed/native runtime 的 secretless 验收只记 PARTIAL；它不影响安装、生命周期和回滚证据。Go race 因锁定构建 CGO=0 不可用，已由并发压力测试覆盖本次 Patch 004 的共享状态风险。

## 八、GitHub Actions 功能证据

最终功能证据 Run：`33273341357`

URL：`https://github.com/xiaochuqing-dev/AI-Agent-Desktop/actions/runs/33273341357`

- Production dependency and import acceptance：success，Job `99155671179`
- Platform-independent core compatibility：success，Job `99155671269`
- Windows-first quality gates：success，Job `99155671352`
- Locked cc-connect Windows artifact and isolated acceptance：success，Job `99156020828`

上传产物：

- `ai-agent-desktop-0.4.1-prebeta-windows-x64`：Artifact `9720889896`，126340610 bytes，GitHub digest `sha256:99349df00159bbb26b0d1b013a0b8190b84d3bd8920f64cb802c927e11dc70f4`
- `cc-connect-v1.5.0-patchset0.2-17c6106-windows-amd64`：Artifact `9720890261`，54279924 bytes，GitHub digest `sha256:9368d97911e7f5b71e500da29007299081dcbc123f7df0b2f137e03b75e2470e`

前一轮 Run `33273131012` 仅因 Windows checkout 把字节级 TOML fixture 转为 CRLF 而失败。提交 `725d371bf2f662fc456fdf4d5df80900f4821624` 用 `.gitattributes` 固定 fixture 为 LF；模拟 `core.autocrlf=true` checkout 和上述最终 Run 均验证通过。

## 九、保护边界与剩余事项

本轮没有修改 `reference-baseline/`，没有接管历史外部运行体，没有写入真实 Bot/Provider Secret，没有修改 PATH、注册表、计划任务或 junction，也没有发送真实 Telegram 消息。

仍需人工或目标环境完成：

1. 使用当前 `0.4.1-prebeta` GUI 完成 Telegram 三 Bot/六链路与 Hermes Native Telegram 用户验收。
2. 在物理 Windows 10 x64 普通用户环境完成候选包验收。
3. 完成 MSI/正式安装器、卸载、快捷方式、代码签名和 Release Asset 流程。
4. 若要消除 management API 全网卡监听、Group Chat 过滤和 deep health 限制，需要上游能力或后续独立设计。

因此，本轮“v1.5.0 融合升级、Patch 收敛、自动回归和 GitHub 产物交付”已完成；正式发布门禁仍按上述边界保持 PARTIAL。

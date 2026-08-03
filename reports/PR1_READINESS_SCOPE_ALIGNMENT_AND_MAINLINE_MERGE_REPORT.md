PR #1 Readiness、产品范围对齐与主线合并报告
===========================================

报告状态：合并前收口版，合并和分支清理字段将在 main 上回写最终事实。

一、Executive Summary
---------------------

PR #1 基于既有 Control Plane Runtime 收口，没有重做 ADR 或骨架。已修复 OpenAPI 外部引用 CI、状态过度报绿和空 Diagnostic 聚合，新增 CC Switch 只读发现，完成 Windows + Telegram 三 Agent 产品范围、Integration First、Telegram 已知限制和下一阶段事实源对齐。当前仍未实现真实安装、配置或凭据写入、生命周期接管、Telegram 自动绑定、六链路自动验收或 GUI。

二、实际起点
------------

- 开始时间：2026-08-04T03:13:33+08:00
- 开始时 origin/main：eafeed921ff27407856f69d8e17b86cf17bd9a52
- 开始时 PR #1 Head：56ad88c76ef39a2524f87d2d3a3101eb4d46918d
- 分支：phase/control-plane-readiness-slice
- PR：#1，OPEN、MERGEABLE、mergeStateStatus=UNSTABLE
- 开始时 CI：Run 30607505672 与 30607482854；Ubuntu 成功，Windows-first 在 OpenAPI lint 失败

三、OpenAPI lint 根因
--------------------

工作流把 YAML 加载成字典后直接调用 openapi-spec-validator，没有传入 OpenAPI 文件 URI。相对外部引用 ./core-models.schema.json 因失去基础 URI而无法解析。

四、修复方式
------------

新增 control-plane/scripts/validate_contracts.py，使用 openapi_spec_validator.readers.read_from_filename 获取 spec 与 base_uri，再显式传给 validate。脚本同时使用 jsonschema 校验 core-models.schema.json 和 event-envelope.schema.json，可从任意工作目录运行。CI 保留 OpenAPI lint 门禁并改为调用该脚本。

五、新增回归测试
----------------

- 从 pytest 临时目录执行契约脚本，验证跨 cwd 的相对外部引用解析
- 配置文件与 Token 引用存在不得产生 running_healthy
- unknown 不进入 ready_items
- blockers、warnings、摘要与建议动作一致
- 探针失败生成脱敏 Diagnostic，不泄露异常、堆栈或私有路径
- CC Switch installed、not_installed、unknown 三态

六、状态聚合审查结果
--------------------

Hermes、cc-connect 和 Telegram Config 原实现可能仅凭安装或配置资料存在返回 running_healthy。现已改为：配置资料存在仅使 configuration=unknown，runtime/health 无直接证据时为 unknown，UserStatus 不报绿。Claude Code 与 Codex 也增加可解释的可执行文件 Condition。

七、Diagnostic 聚合修复
----------------------

ReadinessReport 现在返回真实结构化 blockers 与 warnings。稳定 code 覆盖未安装、配置缺失或冲突、认证、运行失败、健康异常、状态未验证、更新和 Adapter 失败。Diagnostic 只包含公开组件 ID、正交状态和 Condition reason，不含 Secret、私有路径或堆栈。GET /diagnostics 返回最新报告同一组 Diagnostic。

八、CC Switch 发现结果
---------------------

- Adapter ID：cc-switch-discovery
- Component ID：cc-switch
- 发现入口：CC-Switch.exe 的 PATH 与官方 ccswitch 协议注册
- 本机只读结果：installed
- version：unknown，未获得可靠无副作用版本证据
- configuration/authentication/runtime/health/update：unknown
- 写配置或读取 Secret：未执行

九、产品范围回写
----------------

产品定位已收窄为“面向 Windows 开发者的 Telegram AI 编程团队安装、配置、管理、诊断与恢复中心”。首发固定 Windows 10/11、Telegram、Hermes、Claude Code、Codex、cc-connect、可选 CC Switch；PySide6 是未来 GUI 首选。

用户可见 Hermes Bot、Claude Code Bot、Codex Bot。目标链路固定为三个 Agent 各自私聊与群聊共六条。用户未来只输入模型账号或 API 凭据和三个 Bot Token；User ID、Group/Chat ID、配置、端口、Hook、Session 与后台启动由产品未来自动处理。以上自动化当前未实现。

十、Telegram 已知边界
--------------------

群聊主要链路与 Hermes 私聊已有 2026-07-28 高等级证据。Claude Code/Codex 私聊基本可用但正式矩阵待补。/start 等命令存在偶发识别边界；普通消息成功不能证明命令、Topic 或 Session 隔离可用。当前未发现阻断性体验 Bug，本阶段没有重构路由、执行真实 E2E 或发送消息。

十一、Integration First
-----------------------

权威文档现已明确：不重写 Hermes、Claude Code、Codex、cc-connect，不自研通用 Telegram Bridge，不重复开发完整 Provider 管理器。cc-connect 是 V1 核心桥梁，CC Switch 是推荐可选入口。每个作用域同时只有一个 ManagementOwner，本产品与 CC Switch 禁止双写。

十二、主要修改文件
------------------

- CI 与契约：.github/workflows/control-plane-ci.yml、control-plane/scripts/validate_contracts.py、control-plane/tests/test_contract.py
- 状态与诊断：control-plane/control_plane/adapters/discovery.py、application/discovery_service.py、api/app.py 及对应测试
- 顶层事实源：README.md、00_START_HERE.md、01_CURRENT_STATE.md、02_PRODUCT_VISION.md、03_LATEST_PRODUCT_DECISIONS.md、05_NEXT_PHASE.md、SECURITY_REVIEW.md
- 产品事实源：product/PRODUCT_CONSTITUTION.md、COMPONENT_POSITIONING.md、MODEL_CONFIGURATION_OWNERSHIP.md、TEN_MINUTE_ONBOARDING.md、ARCHITECTURE_NON_GOALS.md，以及三个 Telegram/Integration First 专题文档
- 设计与机器事实：architecture/control-plane-v1/README.md、09_MIGRATION_AND_FIRST_VERTICAL_SLICE.md、contracts/control-plane-v1/ 两个相关契约描述
- 交接与报告：next-agent/NEXT_AGENT_PROMPT.txt、两份 reports 文档

十三、本地验证命令与结果
------------------------

- ruff check .：通过
- ruff format --check .：通过
- mypy control_plane tests scripts：通过，33 个源文件
- pytest -q：45 passed
- python scripts/validate_contracts.py：OpenAPI、core-models、event-envelope 通过
- Secret 扫描：pytest 安全门禁通过；仓库额外扫描仅命中合成脱敏测试，非预期 Secret 文件 0
- 文档内部链接：56 个 Markdown 文件，断链 0
- Git diff：src/ 与 integrations/cc-connect/patches/ 变更 0；Control Plane 新增 Telegram 网络调用 0；git diff --check 通过

十四、GitHub Actions
-------------------

- 修复前：Run 30607505672、30607482854；Windows 失败，Ubuntu 成功
- OpenAPI 修复验证：Run 30845203367、30845203103；Windows、Ubuntu、pytest、OpenAPI lint 全部成功
- PR 最终 Run ID、URL 与状态：待最终推送后回写

十五、PR 最终状态
----------------

待全量 CI 通过后回写最终 Head、mergeable 与 merged 状态。

十六、合并方式
--------------

待合并后回写。使用仓库允许的正常 Merge 或 Squash Merge，不改写历史，不 force push。

十七、main 最终 SHA
------------------

待合并后回写。

十八、远端阶段分支删除
--------------------

待 PR 合并后删除 origin/phase/control-plane-readiness-slice 并回写结果。

十九、本地阶段分支删除
--------------------

待切换 main 后删除 phase/control-plane-readiness-slice；旧本地阶段引用也一并清理，最终只保留 main。

二十、最终分支列表
------------------

待清理后回写。

二十一、最终 git status
----------------------

待 main 最终报告提交并推送后回写。

二十二、未解决问题
------------------

真实安装、配置或凭据写入、生命周期接管、Telegram 自动绑定、六链路自动验收、正式 GUI、事件跨重启持久化与 Alembic migration 未实现。它们均已标为 planned、unknown 或 unsupported，不阻塞本 PR 的只读收口目标。

二十三、下一阶段
----------------

cc-connect 单组件真实安装纵向切片。仅实现用户显式确认、可审计 Operation、可取消、安装前快照、来源与版本锁定、安装执行、唯一配置所有权、健康验证、失败回滚和卸载/恢复。

二十四、回滚方式
----------------

合并后代码回滚使用对 PR 合并提交的正常 git revert。Control Plane 独立运行，可停止其进程；本阶段没有真实配置、凭据、服务或 Telegram 副作用需要环境回滚。不得 force push。

二十五、能力标签
----------------

- implemented/read_only：Control Plane 基础服务、发现、Readiness、Diagnostic、Dry-run、Operation/SSE、脱敏、7 个 Adapter
- unsupported：真实安装、配置或凭据写入、启动/停止/重启、深度健康检查
- planned：cc-connect 单组件安装、Telegram 自动绑定、六链路自动验收、正式 GUI
- unknown：没有直接证据的配置、认证、运行、健康、更新、命令、Topic 与 Session 隔离状态
- experimental：没有进入稳定产品验收的局部或未来能力，不得作为已完成能力宣传

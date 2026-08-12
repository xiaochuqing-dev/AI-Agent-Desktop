Integration First 集成优先政策
===============================

一、原则
------

1. 不重新开发 Hermes、Claude Code、Codex 或 cc-connect。
2. 不自研替代 cc-connect 的通用 Telegram Bridge。
3. 不重复开发完整 Provider 管理器，优先集成成熟入口。
4. 通过 Adapter、受控调用、只读发现、深链接、配置所有权和生命周期管理集成上游。
5. Adapter 不得把上游缺失能力虚报为 available。
6. 每个配置作用域同一时刻只有一个 ManagementOwner。
7. 本产品与 CC Switch 不得同时写同一供应商配置作用域。

二、职责边界
------------

Hermes 负责编排和 Hermes Bot；Claude Code、Codex 是独立编码 Agent；cc-connect 负责两个编码 Agent 与 Telegram 的核心桥接及 Project/Session；CC Switch 是可选供应商配置入口；Control Plane 负责统一管理；当前 PySide6 GUI 只消费 Control Plane 契约。GUI 的 onboarding snapshot、Telegram binding、Dashboard 和 Diagnostics 都不能绕过 Control Plane 直接读写上游。

三、能力与证据
--------------

找到可执行文件只证明安装证据，找到配置文件只证明存在，找到 Token 引用只证明引用资料存在。运行、健康、认证、命令、路由和 Session 隔离必须分别有直接证据，没有证据时返回 unknown。

四、变更所有权
--------------

真实写入前必须确定 ManagementOwner、备份与 revision。所有者切换经用户确认和两阶段交接；冲突时保持只读并生成 Diagnostic，不自动合并或覆盖。

产品管理元数据与上游原生配置分开保存。cc-connect 原生 TOML 只由绑定锁定 commit 的 Renderer 生成，不能把 Owner、Operation、审计或 CredentialRef 字段塞进上游 Schema。Secret 只以锁定环境变量占位符进入 TOML，并在启动时从 CredentialBackend 注入目标子进程。

五、当前可升级边界
------------------------

cc-connect 的已安装版本只从 artifact lock、manifest、current 指针和持久化记录获取，不使用 latest。ArtifactProvider、UpdateSource、CompatibilityRule 与 MigrationPlan 已形成稳定内部边界，但本阶段不执行自动更新。Hermes 无实现的更新源准确返回 unsupported。

CC Switch 作为 ExternalToolProvider，只基于公开可执行入口做检测和普通打开。其安装、更新、配置和所有权能力无稳定证据时为 unknown，不读私有数据库、不读 Secret、不自动点击 GUI。

external cc-connect 检测区分 installed、process、port、supervisor、configuration 和 owner。PATH 中仅发现外部可执行文件不阻塞产品实例；相同目标端口、相同配置作用域或外部 Supervisor 才构成硬冲突，且产品不停止或修改外部对象。

六、当前 GUI 交付边界
--------------------

GUI 四步流程已升级到 `0.3.0-prebeta`，真实 Agent Detection 由产品自身只读实现，不依赖 CC Switch runtime；只参考 CC Switch 公开 detection 策略，未复制第三方代码。Demo 仍只用于截图/测试。final3 Windows 11 candidate 已通过 validator；新 GUI Telegram 为 `PENDING USER LIVE VALIDATION`，Windows 10 为 `PENDING WINDOWS 10 VALIDATION`，MSI/签名为 `DEFERRED`。

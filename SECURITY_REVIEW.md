安全审查
========

更新时间：2026-08-04
结论：安全门禁通过；无 Secret 持续运行验收为 PARTIAL

一、仓库内容
------------

未发现真实 Token、API Key、Bearer、Bot Token、Telegram 数字标识、用户名、机器名、个人消息正文、数据库、日志、PID、Session 或 Transcript。配置示例继续使用占位符。

二、Control Plane 安全边界
--------------------------

- 本地 API 仅允许 loopback，使用 Bearer，禁止 URL query token。
- API、Diagnostic、ReadinessReport 和结构化输出统一脱敏。
- SecretRef 不承载明文；SQLite 不作为 Secret Vault。
- Telegram Adapter 只判断配置或 Token 引用文件是否存在，不读取内容，不验证或输出 Token。
- CC Switch Adapter 只检查 PATH 与官方 ccswitch 协议注册，不读取供应商配置或 Secret。
- Diagnostic 不包含私有路径、异常堆栈或底层配置正文。
- 安装下载仅允许锁定 HTTPS 主机并保留 TLS 校验；重定向、大小、文件名、平台、架构和 SHA256 均在执行前校验。
- 安装目标限制在 platformdirs 生成的当前用户 LocalAppData 产品目录，拒绝路径穿越、符号链接和 junction 逃逸。
- 健康探针使用参数数组、隔离环境、临时配置、随机 loopback 端口、无窗口进程和进程树清理，不读取真实用户配置。
- 产品配置仅能写入固定的产品自有路径；使用不可变计划、revision、备份、同目录临时文件、fsync、os.replace、重解析和回滚。
- 生命周期启动使用参数数组、shell=False、固定 cwd、环境白名单和 Windows 无窗口标志；停止前核验 PID 创建时间、exe 路径/SHA256、命令摘要与产品所有权。
- Windows Credential Manager 适配器本阶段只返回 unknown，不读取或写入任何真实 Secret。

三、本阶段无副作用证明
----------------------

只在临时、非系统盘、含中文/空格/括号的隔离产品目录中安装、写入合成配置并尝试运行锁定版 cc-connect。未修改真实配置、凭据、系统 PATH、注册表、计划任务、Watchdog、Windows Service、Reference Baseline 或外部进程；未执行真实 Telegram E2E；未发送任何真实消息。external/conflict Owner 会阻断操作，不自动接管。

四、验证
--------

Control Plane 测试覆盖 Secret 扫描、配置竞态/漂移/回滚、路径逃逸、Operation 并发/取消/恢复、PID 复用、exe SHA256、端口冲突、所有权冲突、进程崩溃和 Control Plane 重启。真实 Windows 隔离验收还检查无真实 Secret/Telegram/PATH/外部状态变更与无残留进程。最终证据记录于 reports/CC_CONNECT_MANAGED_LIFECYCLE_CONFIGURATION_AND_INTEGRATION_BOUNDARIES_REPORT.md。

五、分发限制
------------

当前 cc-connect 产物 signature_status=unsigned。系统不会绕过 SmartScreen、关闭 Defender 或添加白名单；正式外部分发体验仍受 Windows 未签名提示影响。

安全审查
========

更新时间：2026-08-04
结论：本阶段通过

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

三、本阶段无副作用证明
----------------------

只在临时 platformdirs LocalAppData 中安装并清理产品管理版本。未修改真实配置、凭据、系统 PATH、全局 npm、计划任务、Watchdog、junction 或运行中服务；未停止或重启 Hermes/cc-connect；未执行真实 Telegram E2E；未发送任何真实消息。ManagementOwner 为 external 时保持 external，不自动接管生命周期。

四、验证
--------

Control Plane 测试包含源码 Secret 扫描、脱敏正反例、API 响应、Diagnostic、非法 URL、摘要与 Manifest 不匹配、路径逃逸、并发、取消、回滚失败和重启恢复。真实 Windows 隔离验收还检查合成 Token 不落盘、PATH 与外部 cc-connect 不变、无残留进程。最终证据记录于 reports/CC_CONNECT_WINDOWS_ARTIFACT_AND_INSTALLATION_SLICE_REPORT.md。

五、分发限制
------------

当前 cc-connect 产物 signature_status=unsigned。系统不会绕过 SmartScreen、关闭 Defender 或添加白名单；正式外部分发体验仍受 Windows 未签名提示影响。

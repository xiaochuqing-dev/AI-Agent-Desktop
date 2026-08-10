ADR-001 Control Plane 实现语言与 Web/API 框架
=============================================

状态: Accepted / Frozen
日期: 2026-07-31

上下文
------

Control Plane v1 需要一个独立运行、绑定 loopback 的本地服务,承载 HTTP/JSON + SSE 本地 API、Operation 状态机、Provider/Adapter 边界、只读发现与脱敏诊断。当前最小 GUI 已按 PySide6 + Qt Widgets + QSS 实现；完整发布体验仍需独立门禁。

提示词默认推荐方向:Python 3.12+、FastAPI/Starlette、Pydantic v2、SQLite、psutil、packaging、platformdirs、结构化日志成熟库,后续使用成熟 Windows Service Wrapper。

提示词同时要求:必须 Windows-first;必须便于未来与 PySide6 GUI 配合;必须支持后台独立运行;必须便于打包测试升级;必须避免同时维护 Python、Rust、TypeScript 三套核心逻辑;不得仅凭个人偏好选型;不得重复造轮子(不自行实现 HTTP 服务器、OpenAPI/Schema 基础设施、通用日志框架、通用配置解析器、通用事件总线)。

决策
----

采用默认 Python 路线:

1. 实现语言:Python 3.12+。
2. Web/API 框架:FastAPI(基于 Starlette + Pydantic v2),ASGI 服务器用 uvicorn。
3. SSE:使用 sse-starlette,不自建推送通道。
4. 数据校验与模型:Pydantic v2,领域模型与 API 模型共用 Pydantic 类型,契约 JSON Schema 由 Pydantic 导出并与 contracts/control-plane-v1/core-models.schema.json 对齐校验。
5. 系统与进程信息:psutil(成熟、Windows 支持完善)。
6. 版本解析:packaging(语义化版本解析,不自行实现)。
7. 路径解析:platformdirs(用户数据/缓存目录,不写死用户名与绝对路径)。
8. 日志:标准库 logging + 结构化处理器,不引入通用日志框架,所有敏感字段在 Formatter 层脱敏。
9. 不引入 Node、Rust、.NET 作为本阶段核心运行依赖。

替代方案
--------

A. .NET / ASP.NET Core:Windows 原生性好,但与未来 PySide6(Python)GUI 分属两套运行时,核心逻辑会分裂为 Python + C# 两套;且引入额外运行时与打包链。不采用。

B. Rust(axum / actix):性能与内存优秀,但首片以只读发现、状态聚合、脱敏为主,Rust 的开发与维护成本对本切片收益不匹配;且会形成 Python(GUI)+ Rust(Control Plane)两套核心逻辑。不采用。

C. Node.js / TypeScript(Fastify / NestJS):与未来 PySide6 不同语言,核心逻辑分裂;Windows 后台宿主与本地凭据管理生态弱于 Python。不采用。

D. 裸 Starlette + 手写 OpenAPI:比 FastAPI 更轻,但会丢失自动 OpenAPI 生成与校验集成,增加自实现负担,违反“不重复造轮子”。不采用。

后果
----

正面:
- 单语言核心,与未来 PySide6 GUI 同语言,领域模型可被 GUI 侧直接复用类型。
- FastAPI 原生 OpenAPI 3.1 生成与 SSE 支持,直接服务契约测试。
- psutil、platformdirs、packaging 均为成熟活跃库,Windows 支持完善,许可兼容(Apache-2.0 / BSD / MIT 系)。
- 冷启动与内存对本切片(只读发现 + 状态聚合)完全够用,无需极限优化。

负面 / 约束:
- Python 进程冷启动约数百毫秒量级,比原生语言慢,对本场景可接受。
- 打包体积(PyInstaller 等)在后续阶段评估,本阶段不打包发行。
- uvicorn 在 Windows 上的多 worker 模式有限制,本阶段单 worker 足够,且 Control Plane 只绑 loopback、无高并发需求。

依赖与供应链
------------

第三方依赖逐项登记(进入最终发行包与否后续评估):
- fastapi / starlette / uvicorn:BSD-3-Clause,活跃维护,核心 Web/API,不进 Adapter 隔离边界外。
- pydantic v2:MIT,活跃,模型校验与 Schema 导出。
- sse-starlette:BSD-3-Clause,SSE 承载。
- psutil:BSD-3-Clause,进程与系统信息采集,仅 WindowsSystemDiscoveryAdapter 与健康探针使用,可被 Adapter 隔离。
- packaging:Apache-2.0 / BSD,语义化版本解析。
- platformdirs:MIT,用户目录解析。
- keyring:MIT,凭据后端封装(见 ADR-004)。
- sqlalchemy 2.0 / alembic:MIT,持久化(见 ADR-004 / ADR-002)。

以上均不进入“通用 HTTP 服务器自实现”“通用事件总线自实现”“通用日志框架自实现”等禁止范围,均为成熟库的直接使用。

回退条件
--------

若出现以下任一明确阻塞证据,停止编码并提交冲突报告,不静默换栈:
1. FastAPI + sse-starlette 在 Windows loopback 下 SSE 断连重连、Last-Event-ID 游标无法稳定实现契约 05 §178-186 的去重与 410 语义。
2. Pydantic v2 导出的 JSON Schema 无法与 core-models.schema.json(Draft 2020-12)对齐到可契约测试通过。
3. 打包或运行时依赖在干净 Windows 上无法以一条命令安装并启动。

回退路径:不换语言,只换 ASGI 层(Starlette / litestar)或 Schema 导出方式,领域层(domain)不依赖任何具体 Web 框架,故可仅替换 api/ 层。

未来重审触发器
----------------

1. 与 PySide6 GUI 集成时发现同进程内嵌 ASGI 不可行,需重新评估 GUI 与 Control Plane 进程边界。
2. 打包发行阶段评估体积与冷启动是否可接受。
3. 契约测试或安全测试暴露 FastAPI 默认行为与 loopback 安全边界冲突。
4. 上游 FastAPI / Pydantic 主版本破坏性变更。

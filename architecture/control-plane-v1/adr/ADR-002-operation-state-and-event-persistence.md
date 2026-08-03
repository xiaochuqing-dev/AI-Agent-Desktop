ADR-002 Operation、事件与事务型状态的持久化方案
=================================================

状态: Accepted / Frozen
日期: 2026-07-31

上下文
------

Control Plane v1 需要持久化:Operation(状态机 queued/running/cancel_requested/succeeded/failed/canceled)、幂等记录(Idempotency-Key、方法、资源、body 摘要、Operation ID)、Component 状态快照与 revision、Diagnostic 索引、Adapter 私有到通用的 ID 映射、事件 sequence/epoch/resourceversion(用于 SSE 去重与游标恢复)。

契约要求(05 §126-144、event-envelope.schema.json):Operation 至少保留到 GUI 重连与用户查看;重启后保留幂等记录;无法确认外部副作用时 Operation 转 failed/unknown diagnostic,先探测再允许人工重试;同一 epoch 内 sequence 严格递增;事件与状态写入在同一产品事务中分配 resourceversion。

提示词默认推荐:SQLite,SQLAlchemy 2 + Alembic,或有充分证据的更轻替代;不引入外部数据库,不直接复用 multiagent.db。

决策
----

1. 持久化引擎:SQLite,启用 WAL 模式,存放在 platformdirs.user_data_dir(本产品数据目录),不写死用户名与绝对路径。文件名 control_plane.db。
2. 访问层:SQLAlchemy 2.0(声明式 ORM),迁移用 Alembic。领域层(domain)不依赖 SQLAlchemy 类型,只依赖领域模型;infrastructure/persistence 层做 ORM 映射。
3. 不复用 src/ 下 hermes-adapter 的 multiagent.db,Control Plane 状态与 Hermes transcript 物理隔离。
4. 事务边界:Operation 状态推进、幂等记录写入、Component 状态快照更新与对应事件 resourceversion 分配,在同一 SQLAlchemy 事务内提交,保证契约“状态写入与对应事件在同一产品事务中分配 resourceversion”。
5. 重启恢复:启动时读取未终止 Operation(queued/running/cancel_requested),对无法确认外部副作用者标记为 failed 并生成 Diagnostic(code=OPERATION_RECOVERY_UNKNOWN),先探测再允许人工重试,禁止自动重放未知副作用。
6. 保留期:Operation 与幂等记录保留窗口为开放实现参数(默认 7 天,可在配置中调整),过期按 05 §136 与 10 §56 的“明确冲突或快照恢复”处理,不静默丢失。具体数值在实现时以可配置常量标注含义与单位。
7. 事件游标:epoch/sequence/resourceversion 持久化,SSE Last-Event-ID 恢复从下一条重放;游标过期返回 410 EVENT_CURSOR_EXPIRED,客户端先取快照再无游标订阅。

替代方案
--------

A. 裸标准库 sqlite3:最轻,无新依赖。但缺少迁移管理,Schema 演进时需手写迁移脚本,长期维护成本高,且易引入手写 SQL 错误。不作为主方案,但保留为极端轻量化退路。

B. SQLModel:比 SQLAlchemy 更薄,与 Pydantic 集成更直接,但生态与迁移工具成熟度不及 SQLAlchemy + Alembic,且复杂查询表达力弱。不采用。

C. DuckDB:分析型,本场景是 OLTP(状态机、幂等、事件游标),不匹配。不采用。

D. 外部数据库(PostgreSQL 等):违反“不引入外部数据库”与 Windows-first 本地零依赖原则。不采用。

后果
----

正面:
- 单文件 .db,易备份、易回滚、易随用户数据目录迁移。
- WAL 模式支持读并发,满足“GUI 读取快照期间 Operation 写入”。
- Alembic 提供前向迁移与降级路径,Schema 演进可控。
- 事务边界明确,满足契约 resourceversion 与幂等语义。

负面 / 约束:
- SQLite 并发写为单写锁,本场景写量低(只读发现 + 少量 Operation),无瓶颈;若未来写量上升需评估。
- WAL 在网络文件系统上不可靠,需确保数据目录在本地磁盘(实现时校验)。
- Alembic 迁移需纳入 CI 校验,避免 Schema 漂移。

回退条件
--------

1. SQLite WAL 在 Windows 上出现无法解释的锁冲突或损坏(实测可复现)。
2. 并发写竞争导致 Operation 推进频繁超时且无法通过调整事务粒度解决。
3. 事件游标与 sequence 持久化在重启后无法稳定恢复(契约测试失败)。

回退路径:领域层不依赖 SQLAlchemy,可替换为裸 sqlite3 或其他嵌入式存储,只改 infrastructure/persistence 层。

未来重审触发器
----------------

1. 单机写并发出现实际瓶颈(未来多 Provider 高频状态更新)。
2. 需要跨机器状态同步(将引入新主版本契约与外部存储,属 /api/v2 范畴)。
3. 数据目录需随用户迁移(触发备份/迁移实现,属阶段 3)。

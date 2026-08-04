组件定位 COMPONENT_POSITIONING
==============================

Hermes
------

默认编排中枢与 Hermes Bot 运行主体，负责治理、委派和汇总。本产品通过 Adapter 集成，不重写其核心。

Claude Code
-----------

独立编码 Agent，通过 cc-connect 接入 Telegram。私聊与群聊能力必须分别验证，不能用普通消息证据推断命令或 Session 隔离已通过。

Codex
-----

独立编码 Agent，通过 cc-connect 接入 Telegram，与 Claude Code 并列，状态和链路证据独立记录。

cc-connect
----------

V1 核心桥梁，承载 Claude Code/Codex 与 Telegram 的连接、Project 和 Session。当前不得把它描述为可忽略的辅助层，也不得自研通用 Bridge 替代它。未来替换必须有完整迁移、六链路回归和回滚证据。

Telegram
--------

首发且本阶段唯一 Channel。三个 Bot 与六条私聊/群聊链路是固定产品范围；不在本阶段加入其他渠道。

CC Switch
---------

推荐但非强制的供应商、模型和 API 配置入口。Control Plane 本阶段只做公开可执行入口检测和普通打开，不读取或写入 Provider 配置。启用管理时必须遵守唯一 ManagementOwner。

Control Plane
-------------

统一承担发现、安装计划、配置权、状态、生命周期、诊断、更新评估和回滚。当前只对产品自有 cc-connect 实现安装、最小配置和生命周期变更；其他组件保持只读或 unsupported。锁定版无 Secret 持续运行证据为 PARTIAL。

GUI
---

未来首选 PySide6，只调用 Control Plane 稳定契约，不直接写 Hermes、cc-connect、Claude Code、Codex、Telegram 或 CC Switch 私有配置。

dual_agent 与 cc-connect Patch
-----------------------------

均为当前兼容层，本阶段不扩大。只有上游能力补齐且 Reference Baseline 与六链路回归通过后才可逐项退场。

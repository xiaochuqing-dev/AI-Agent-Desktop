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

统一承担发现、安装计划、配置权、状态、生命周期、诊断、更新评估和回滚。当前已对产品自有 cc-connect 实现安装、合法 Claude/Codex 原生配置、Secret 注入和生命周期；对 Telegram 实现安全凭据、身份与绑定；对已安装但 Telegram 未配置的 Hermes，通过官方公开 `.env` 与 Gateway CLI 实现最小接入、readiness、冲突计划和 Gateway 生命周期，已有配置不静默接管。最小 GUI 通过 onboarding/dashboard/Telegram API 消费这些状态。Windows 11 candidate 已通过本地验证；整体因新 GUI live、Hermes Native live 与 Windows 10 尚未验证仍为 PARTIAL。

GUI
---

当前实现为 PySide6 + Qt Widgets + QSS `0.4.0-prebeta`，包含 Welcome、四步 Onboarding、真实 Agent 状态、严格 Runtime、QR/深链接、Hermes readiness/conflict、Live E2E、Dashboard 和 Diagnostics。它只调用 Control Plane 稳定契约，不读取 Hermes 私有数据，不直接写 Claude Code、Codex、Telegram 或 CC Switch 私有配置；Hermes 仅使用官方公开 `.env` 的两个 allowlisted Telegram key，产品自有 cc-connect 受管路径可写。新 GUI Telegram 与 Hermes Native Telegram 为 `PENDING USER LIVE VALIDATION`，Windows 10 为 `PENDING WINDOWS 10 VALIDATION`。

dual_agent 与 cc-connect Patch
-----------------------------

均为当前兼容层，本阶段不扩大。只有上游能力补齐且 Reference Baseline 与六链路回归通过后才可逐项退场。

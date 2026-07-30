"""委派接口定义。

Delegator 是 dual_agent 与外部世界的唯一接缝：执行一次“把消息交给某 Agent”
的派发，拿回结构化结果。适配层把真实 relay_client.send 包装成 Delegator 注入。

这样 dual_agent 本身不 import relay_client / cc-connect / Telegram，可独立测试
与复用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Protocol, runtime_checkable


class DelegateStatus(str, Enum):
    # 单次委派的状态：成功 / 失败（Agent 报错或不可达）/ 超时
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class DelegateResult:
    # 一次委派的结构化结果。reply 为 Agent 的正式输出原文（成功时），
    # 失败时 reply 可能为空，error 存原因。
    # agent 可在构造时省略，由 Delegator/runner 在调用时回填（便于测试构造）。
    status: DelegateStatus
    agent: str = ""
    reply: str = ""
    error: str = ""
    turn: int = 0               # 第几跳，用于审计
    elapsed: float = 0.0        # 耗时秒，用于诊断慢 Agent
    meta: dict = field(default_factory=dict)  # 适配层附加信息（如 relay_session_key）

    @property
    def ok(self) -> bool:
        return self.status == DelegateStatus.SUCCESS

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "status": self.status.value,
            "reply": self.reply,
            "error": self.error,
            "turn": self.turn,
            "elapsed": self.elapsed,
            "meta": dict(self.meta),
        }


@runtime_checkable
class Delegator(Protocol):
    # 可注入的委派协议。实现者只需提供 __call__(agent, message, turn) -> DelegateResult。
    # 适配层注入真实 relay 调用；测试注入 fake。
    def __call__(self, agent: str, message: str, turn: int = 0,
                 **kwargs: Any) -> DelegateResult: ...


# 构造单步消息的回调签名：(agent, step_goal, prior_output_or_empty) -> message
# 顺序模式下，把前一步原始输出注入当前步的上下文，由适配层/调用方决定怎么拼。
BuildStepMessage = Callable[[str, str, Optional[str]], str]

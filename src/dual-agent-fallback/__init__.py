"""双 Agent 闭环执行模块（独立可复用）。

本包定义双 Agent 调度的纯逻辑：并行、顺序、结果聚合、部分失败、防重复。
不依赖 Hermes、Telegram、cc-connect 的任何内部对象，只通过可注入的
Delegator（委派接口）执行实际派发，由适配层注入真实 relay。

适用场景：
  - 并行：让 Claude/Codex 同时各自分析，互不阻塞，收齐后聚合
  - 顺序：先 A 出结果，把 A 的原始输出注入 B，B 再审查/续作
  - 部分失败：单边失败不丢另一边成功结果，聚合时明确标注成败

公开接口：
  Delegator / DelegateResult  - 委派协议
  AgentResults                - 执行结果聚合
  run_parallel / run_sequential - 两种执行路径
  HopLimit                    - 防循环保险丝
"""

from .delegator import Delegator, DelegateResult, DelegateStatus
from .runner import run_parallel, run_sequential, ParallelTarget, SequentialStep
from .aggregate import AgentResults
from .guard import HopLimit

__all__ = [
    "Delegator",
    "DelegateResult",
    "DelegateStatus",
    "AgentResults",
    "run_parallel",
    "run_sequential",
    "ParallelTarget",
    "SequentialStep",
    "HopLimit",
]

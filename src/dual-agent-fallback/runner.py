"""执行路径：并行与顺序。

两条路径都接收一个 Delegator（注入的真实 relay）和一个 HopLimit（保险丝），
返回 AgentResults。纯逻辑，无 IO 假设（IO 全在 Delegator 里）。

场景对应（需求 §B）：
  run_parallel  - 场景1：Claude 检查实现 / Codex 检查风险，两边完成后聚合
  run_sequential- 场景2：先 Claude 给方案，结果注入 Codex 审查
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Callable, List, Optional

from .aggregate import AgentResults
from .delegator import DelegateResult, DelegateStatus, Delegator
from .guard import HopLimit

logger = logging.getLogger(__name__)

# 单次委派的默认超时（秒）。真实 relay 首次 spawn agent 可能要几分钟，
# 600 与 cc-connect [relay] timeout_secs 对齐。
DEFAULT_DELEGATE_TIMEOUT = 600


@dataclass
class ParallelTarget:
    # 并行派发的一个目标：agent + 给它的消息
    agent: str
    message: str
    label: str = ""   # 可选标签，便于结果归属


def run_parallel(targets: List[ParallelTarget],
                 delegator: Delegator,
                 hop_limit: HopLimit,
                 timeout: float = DEFAULT_DELEGATE_TIMEOUT,
                 max_workers: Optional[int] = None) -> AgentResults:
    """并行派发多个 Agent，互不阻塞，收齐后聚合。

    要求（需求 §B1）：
      - 两任务真正并行，第一个慢不阻塞第二个的派发
      - 每个 Worker 只发一次正式结果
      - 两边完成、超时或失败后才结束任务
      - 两边结果归属同一父任务
    """
    results = AgentResults()
    if not targets:
        return results

    # 跳数预检：保险丝已满则不派发
    if hop_limit.would_exceed():
        results.stopped_reason = "跳数超限，停止派发"
        return results

    n = len(targets)
    workers = max(1, min(n, max_workers or n))

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dual-agent") as pool:
        future_to_target = {}
        turn = 0
        for t in targets:
            if hop_limit.would_exceed():
                break
            fut = pool.submit(_delegate_one, delegator, t.agent, t.message, turn, timeout)
            future_to_target[fut] = t
            turn += 1

        # as_completed：谁先完成谁先收，不因慢者阻塞快者的结果回收
        for fut in as_completed(future_to_target, timeout=timeout + 30):
            t = future_to_target[fut]
            try:
                r = fut.result()
            except Exception as exc:
                # 线程异常兜底（Delegator 内部应已捕获，这里是双保险）
                r = DelegateResult(agent=t.agent, status=DelegateStatus.FAILED,
                                   error=f"执行异常: {exc}", turn=0)
            if r.ok:
                hop_limit.record(t.agent, r.reply)
            results.add(r)

    return results


def _delegate_one(delegator: Delegator, agent: str, message: str,
                 turn: int, timeout: float) -> DelegateResult:
    # 单次委派的线程入口：调 Delegator，计时，超时/异常转成结构化结果
    start = time.monotonic()
    try:
        r = delegator(agent, message, turn=turn)
        r.elapsed = time.monotonic() - start
        return r
    except Exception as exc:
        # Delegator 应自己返回 FAILED，但若它抛异常也兜住，不污染线程池
        return DelegateResult(agent=agent, status=DelegateStatus.FAILED,
                               error=f"委派异常: {exc}", turn=turn,
                               elapsed=time.monotonic() - start)


@dataclass
class SequentialStep:
    # 顺序执行的一步：agent + 这一步的目标（goal）+ 可选标签
    agent: str
    goal: str
    label: str = ""


def run_sequential(steps: List[SequentialStep],
                   delegator: Delegator,
                   hop_limit: HopLimit,
                   build_message: Callable[[str, str, Optional[str]], str],
                   timeout: float = DEFAULT_DELEGATE_TIMEOUT) -> AgentResults:
    """顺序执行多步，把前一步原始输出注入下一步上下文。

    要求（需求 §B2）：
      - 第一步完成后才派发第二步
      - 第二步真正看到第一步的有效结果（原始输出，非模糊摘要）
      - 用户指定的 Agent 与顺序严格服从，不交换
      - 只传当前任务所需上下文，不塞整段群聊历史
    build_message(agent, step_goal, prior_output_or_empty) -> message
      由调用方决定怎么把前一步输出拼进当前步消息（适配层职责）。
    """
    results = AgentResults()
    if not steps:
        return results

    prior_output: Optional[str] = None
    turn = 0
    for step in steps:
        if hop_limit.would_exceed():
            results.stopped_reason = "跳数超限，停止派发"
            break
        if hop_limit.is_stalled():
            results.stopped_reason = "连续重复输出，停止"
            break

        message = build_message(step.agent, step.goal, prior_output)
        r = _delegate_one(delegator, step.agent, message, turn, timeout)
        results.add(r)

        if r.ok:
            hop_limit.record(step.agent, r.reply)
            # 把这一步的原始输出作为下一步的输入（真实结果，非摘要）
            prior_output = r.reply
            turn += 1
        else:
            # 单步失败：保留已成功的结果，停止后续顺序（后续依赖前步，无意义）
            # 已成功的结果不丢（results 已记录），这里只是不再继续
            break

    return results

"""结果聚合。

把并行/顺序执行的各 Agent 结果聚合成结构化数据，供适配层交给 Hermes LLM 总结。
本模块不生成总结文本（那是 Hermes 的职责），只提供：谁成功、谁失败、已取得什么、
是否建议重试。

核心约束（需求 §B3 部分失败）：
  - 单边失败不丢另一边成功结果
  - 明确标注每个 Agent 的状态（success/failed/timeout）
  - 给出“已取得的结果”与“是否建议重试”
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .delegator import DelegateResult, DelegateStatus


@dataclass
class AgentResults:
    # 一次双 Agent 任务的聚合结果
    successes: Dict[str, DelegateResult] = field(default_factory=dict)   # agent -> result（成功的）
    failures: Dict[str, DelegateResult] = field(default_factory=dict)    # agent -> result（失败的）
    timed_out: Dict[str, DelegateResult] = field(default_factory=dict)  # agent -> result（超时的）
    stopped_reason: str = ""   # 非正常终止原因（如跳数超限、停滞），空=正常结束

    def add(self, r: DelegateResult) -> None:
        if r.status == DelegateStatus.SUCCESS:
            self.successes[r.agent] = r
        elif r.status == DelegateStatus.TIMEOUT:
            self.timed_out[r.agent] = r
        else:
            self.failures[r.agent] = r

    @property
    def all_agents(self) -> List[str]:
        # 所有涉及的 Agent（成败都算），按成功优先排序，便于稳定输出
        seen: List[str] = []
        for a in list(self.successes) + list(self.failures) + list(self.timed_out):
            if a not in seen:
                seen.append(a)
        return seen

    @property
    def success_agents(self) -> List[str]:
        return list(self.successes.keys())

    @property
    def failed_agents(self) -> List[str]:
        return list(self.failures.keys()) + list(self.timed_out.keys())

    @property
    def has_any_success(self) -> bool:
        return bool(self.successes)

    @property
    def all_failed(self) -> bool:
        return not self.successes and (bool(self.failures) or bool(self.timed_out))

    def success_replies(self) -> Dict[str, str]:
        # 成功 Agent 的原始输出，供总结 prompt 用
        return {a: r.reply for a, r in self.successes.items()}

    def failure_summary(self) -> List[str]:
        # 失败/超时摘要，供总结时明确标注
        lines: List[str] = []
        for a, r in self.failures.items():
            lines.append(f"{a} 失败：{r.error or '未知原因'}")
        for a, r in self.timed_out.items():
            lines.append(f"{a} 超时（{r.elapsed:.0f}s）")
        return lines

    def recommend_retry(self) -> bool:
        # 是否建议重试：有失败且并非全失败时建议重试失败的；全失败时不强建议（需人判断）
        if self.all_failed:
            return False
        return bool(self.failures) or bool(self.timed_out)

    def to_dict(self) -> dict:
        return {
            "successes": {a: r.to_dict() for a, r in self.successes.items()},
            "failures": {a: r.to_dict() for a, r in self.failures.items()},
            "timed_out": {a: r.to_dict() for a, r in self.timed_out.items()},
            "stopped_reason": self.stopped_reason,
            "success_agents": self.success_agents,
            "failed_agents": self.failed_agents,
            "has_any_success": self.has_any_success,
            "all_failed": self.all_failed,
            "recommend_retry": self.recommend_retry(),
        }

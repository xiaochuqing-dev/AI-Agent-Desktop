"""防循环与保险丝。

纯逻辑的跳数与重复限制，不依赖 store。适配层若需持久化审计，可把这里的
状态镜像写入共享 DB，但 dual_agent 自身只持有内存态。

设计原则：
  - 正常并行/顺序不会被保险丝误杀（单任务每 Agent 只派一次，hop=1）
  - 保险丝只防异常：A<->B ping-pong 无限互派、连续重复输出
  - 超过 max_hops 不再派发，聚合时报告“跳数超限停止”
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class HopLimit:
    # 跳数与重复保险丝。一次双 Agent 任务共用一个实例。
    max_hops: int = 12          # 单任务总跳数硬上限（异常防失控，正常远不到）
    max_repeat: int = 3         # 连续近重复输出次数（停滞信号）

    _hop_count: int = 0
    _speaker_sequence: List[str] = field(default_factory=list)
    _last_hash: Optional[str] = None
    _consecutive_repeat: int = 0

    @property
    def hop_count(self) -> int:
        return self._hop_count

    @property
    def consecutive_repeat(self) -> int:
        return self._consecutive_repeat

    def record(self, agent: str, reply: str) -> None:
        # 记一跳：累加跳数、追发言序列、更新重复计数
        self._hop_count += 1
        self._speaker_sequence.append(agent)
        h = _hash_text(reply)
        if h == self._last_hash:
            self._consecutive_repeat += 1
        else:
            self._consecutive_repeat = 0
            self._last_hash = h

    @property
    def ping_pong_detected(self) -> bool:
        # 检测 A<->B 来回乒乓（4 跳以上两轮完整交替）
        seq = self._speaker_sequence
        if len(seq) < 4:
            return False
        tail = seq[-4:]
        return tail[0] == tail[2] and tail[1] == tail[3] and tail[0] != tail[1]

    def would_exceed(self) -> bool:
        # 是否已达跳数上限（调用前判断，达上限则不再派发）
        return self._hop_count >= self.max_hops

    def is_stalled(self) -> bool:
        # 是否停滞（连续重复达到阈值）
        return self._consecutive_repeat >= self.max_repeat


def _hash_text(text: str) -> str:
    # 轻量哈希用于近重复检测，不要求密码学强度
    import hashlib
    return hashlib.md5((text or "").strip().lower().encode("utf-8", "replace")).hexdigest()[:12]

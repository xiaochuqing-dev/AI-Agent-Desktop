# -*- coding: utf-8 -*-
"""dual_agent 单元测试。

用 fake Delegator 验证纯逻辑：并行真并发、顺序传结果、部分失败聚合、防重复保险丝。
不依赖真实 relay / Telegram / Hermes。
"""

import os
import sys
import time
import unittest

# 让测试能 import dual_agent（从测试文件所在目录上溯到项目根）
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dual_agent import (  # noqa: E402
    Delegator, DelegateResult, DelegateStatus,
    AgentResults, HopLimit,
    run_parallel, run_sequential,
    ParallelTarget, SequentialStep,
)


class FakeDelegator:
    # 测试用 fake：按预设返回结果，记录调用顺序与并发情况
    def __init__(self, returns=None, delays=None):
        # returns: {(agent, turn): DelegateResult} 或 {agent: DelegateResult}
        # delays: {agent: 秒} 模拟慢 Agent
        self.returns = returns or {}
        self.delays = delays or {}
        self.calls = []  # [(agent, message, turn, start_time)]
        self._lock_concurrent = []  # 用于并发检测
        import threading
        self._lock = threading.Lock()
        self._active = 0

    def __call__(self, agent, message, turn=0, **kwargs):
        import threading
        with self._lock:
            self._active += 1
            self._lock_concurrent.append(("start", agent, time.monotonic()))
            self.calls.append((agent, message, turn, time.monotonic()))
        # 模拟延迟
        if agent in self.delays:
            time.sleep(self.delays[agent])
        with self._lock:
            self._active -= 1
        # 取预设结果
        key = (agent, turn)
        if key in self.returns:
            r = self.returns[key]
        elif agent in self.returns:
            r = self.returns[agent]
        else:
            r = DelegateResult(agent=agent, status=DelegateStatus.SUCCESS,
                                reply=f"{agent} 默认回复", turn=turn)
        r.agent = agent
        r.turn = turn
        return r


class TestRunParallel(unittest.TestCase):
    # 场景1：双 Agent 并行

    def test_parallel_both_success(self):
        # 两边都成功，结果都收回
        fake = FakeDelegator(returns={
            "claude": DelegateResult(status=DelegateStatus.SUCCESS, reply="实现 OK"),
            "codex": DelegateResult(status=DelegateStatus.SUCCESS, reply="无风险"),
        })
        targets = [ParallelTarget("claude", "检查实现"), ParallelTarget("codex", "检查风险")]
        res = run_parallel(targets, fake, HopLimit())
        self.assertEqual(set(res.success_agents), {"claude", "codex"})
        self.assertEqual(res.success_replies()["claude"], "实现 OK")
        self.assertEqual(res.success_replies()["codex"], "无风险")
        self.assertFalse(res.failed_agents)

    def test_parallel_truly_concurrent(self):
        # 核心：第一个慢不阻塞第二个的派发。两个各 sleep 0.3s，
        # 若串行总耗 >=0.6s，若并行总耗 <0.5s
        fake = FakeDelegator(
            returns={
                "claude": DelegateResult(status=DelegateStatus.SUCCESS, reply="c"),
                "codex": DelegateResult(status=DelegateStatus.SUCCESS, reply="x"),
            },
            delays={"claude": 0.3, "codex": 0.3},
        )
        targets = [ParallelTarget("claude", "m1"), ParallelTarget("codex", "m2")]
        start = time.monotonic()
        res = run_parallel(targets, fake, HopLimit())
        elapsed = time.monotonic() - start
        self.assertTrue(res.has_any_success)
        # 并行应明显快于串行（0.6s），给足余量到 0.5s
        self.assertLess(elapsed, 0.5, f"并行耗时 {elapsed:.2f}s 应 <0.5s，疑似串行")

    def test_parallel_slow_does_not_block_fast(self):
        # Claude 慢（0.4s）、Codex 快（0.05s），Codex 应先收回且不受 Claude 阻塞
        fake = FakeDelegator(
            returns={
                "claude": DelegateResult(status=DelegateStatus.SUCCESS, reply="c-late"),
                "codex": DelegateResult(status=DelegateStatus.SUCCESS, reply="x-fast"),
            },
            delays={"claude": 0.4, "codex": 0.05},
        )
        targets = [ParallelTarget("claude", "m1"), ParallelTarget("codex", "m2")]
        res = run_parallel(targets, fake, HopLimit())
        # 两边都成功
        self.assertEqual(set(res.success_agents), {"claude", "codex"})
        # Codex 耗时应远小于 Claude
        self.assertLess(res.successes["codex"].elapsed, res.successes["claude"].elapsed)

    def test_parallel_one_failed_not_lose_other(self):
        # Claude 成功、Codex 失败：成功结果不丢，失败明确标注（需求 §B3）
        fake = FakeDelegator(returns={
            "claude": DelegateResult(status=DelegateStatus.SUCCESS, reply="实现 OK"),
            "codex": DelegateResult(status=DelegateStatus.FAILED, error="Codex 不可达"),
        })
        targets = [ParallelTarget("claude", "m1"), ParallelTarget("codex", "m2")]
        res = run_parallel(targets, fake, HopLimit())
        self.assertIn("claude", res.successes)
        self.assertIn("codex", res.failures)
        self.assertEqual(res.failures["codex"].error, "Codex 不可达")
        self.assertTrue(res.recommend_retry())  # 有失败且非全失败 -> 建议重试

    def test_parallel_one_timeout_not_block_other(self):
        # Codex 超时、Claude 正常：Claude 结果收回，Codex 记超时
        fake = FakeDelegator(
            returns={
                "claude": DelegateResult(status=DelegateStatus.SUCCESS, reply="c"),
                "codex": DelegateResult(status=DelegateStatus.TIMEOUT, reply="", error="超时"),
            },
            delays={"codex": 0.01},  # 超时是预设状态，不靠真实 sleep
        )
        targets = [ParallelTarget("claude", "m1"), ParallelTarget("codex", "m2")]
        res = run_parallel(targets, fake, HopLimit())
        self.assertIn("claude", res.successes)
        self.assertIn("codex", res.timed_out)

    def test_parallel_all_failed(self):
        fake = FakeDelegator(returns={
            "claude": DelegateResult(status=DelegateStatus.FAILED, error="e1"),
            "codex": DelegateResult(status=DelegateStatus.FAILED, error="e2"),
        })
        targets = [ParallelTarget("claude", "m1"), ParallelTarget("codex", "m2")]
        res = run_parallel(targets, fake, HopLimit())
        self.assertTrue(res.all_failed)
        self.assertFalse(res.has_any_success)
        self.assertFalse(res.recommend_retry())  # 全失败不强建议重试

    def test_parallel_hop_limit_stops(self):
        # 保险丝已满，不再派发
        fake = FakeDelegator(returns={
            "claude": DelegateResult(status=DelegateStatus.SUCCESS, reply="c"),
        })
        hop = HopLimit(max_hops=1)
        hop.record("codex", "x")  # 预占 1 跳
        targets = [ParallelTarget("claude", "m1")]
        res = run_parallel(targets, fake, hop)
        self.assertEqual(res.stopped_reason, "跳数超限，停止派发")
        self.assertEqual(fake.calls, [])  # 没派发


class TestRunSequential(unittest.TestCase):

    def test_sequential_second_sees_first_output(self):
        # 核心：第二步的 message 必须含第一步的原始输出
        seen_messages = []

        def build_msg(agent, goal, prior_output):
            msg = f"目标:{goal}"
            if prior_output:
                msg += f"\n上一步结果:{prior_output}"
            seen_messages.append((agent, msg))
            return msg

        fake = FakeDelegator(returns={
            ("claude", 0): DelegateResult(agent="start", status=DelegateStatus.SUCCESS, reply="方案 A"),
            ("codex", 1): DelegateResult(agent="codex", status=DelegateStatus.SUCCESS, reply="方案 A 可行"),
        })
        steps = [SequentialStep("claude", "给方案"), SequentialStep("codex", "审查")]
        res = run_sequential(steps, fake, HopLimit(), build_msg)

        # 两步都成功
        self.assertEqual(res.success_agents, ["claude", "codex"])
        # 第一步无前步输出
        self.assertNotIn("上一步结果", seen_messages[0][1])
        # 第二步必须含第一步的原始输出"方案 A"（非模糊摘要）
        self.assertIn("方案 A", seen_messages[1][1])

    def test_sequential_honours_explicit_order(self):
        # 用户显式指定先 Codex 后 Claude，不得交换
        order = []

        def build_msg(agent, goal, prior_output):
            order.append(agent)
            return goal

        fake = FakeDelegator(returns={
            ("codex", 0): DelegateResult(agent="claude", status=DelegateStatus.SUCCESS, reply="codex先"),
            ("claude", 1): DelegateResult(agent="claude", status=DelegateStatus.SUCCESS, reply="claude后"),
        })
        steps = [SequentialStep("codex", "先分析"), SequentialStep("claude", "后实现")]
        res = run_sequential(steps, fake, HopLimit(), build_msg)
        self.assertEqual(order, ["codex", "claude"])  # 顺序不被交换

    def test_sequential_first_fails_stops_but_keeps_nothing(self):
        # 第一步失败：后续不继续（依赖前步），且无成功结果
        fake = FakeDelegator(returns={
            ("claude", 0): DelegateResult(agent="codex", status=DelegateStatus.FAILED, error="claude挂了"),
        })
        steps = [SequentialStep("claude", "给方案"), SequentialStep("codex", "审查")]
        res = run_sequential(steps, fake, HopLimit(), lambda a, g, p: g)
        self.assertFalse(res.has_any_success)
        self.assertIn("claude", res.failures)
        self.assertNotIn("codex", res.successes)  # 第二步没跑

    def test_sequential_second_fails_keeps_first(self):
        # 第二步失败：第一步成功结果不丢（需求 §B3）
        fake = FakeDelegator(returns={
            ("claude", 0): DelegateResult(agent="claude", status=DelegateStatus.SUCCESS, reply="方案 A"),
            ("codex", 1): DelegateResult(agent="codex", status=DelegateStatus.FAILED, error="codex挂了"),
        })
        steps = [SequentialStep("claude", "给方案"), SequentialStep("codex", "审查")]
        res = run_sequential(steps, fake, HopLimit(), lambda a, g, p: g)
        self.assertIn("claude", res.successes)
        self.assertIn("codex", res.failures)
        self.assertTrue(res.recommend_retry())


class TestAggregate(unittest.TestCase):

    def test_failure_summary_lists_all(self):
        res = AgentResults()
        res.add(DelegateResult(agent="claude", status=DelegateStatus.SUCCESS, reply="ok"))
        res.add(DelegateResult(agent="codex", status=DelegateStatus.FAILED, error="不可达"))
        res.add(DelegateResult(agent="pi", status=DelegateStatus.TIMEOUT, elapsed=600))
        summary = res.failure_summary()
        self.assertTrue(any("codex" in s and "不可达" in s for s in summary))
        self.assertTrue(any("pi" in s and "超时" in s for s in summary))

    def test_to_dict_roundtrip(self):
        res = AgentResults()
        res.add(DelegateResult(agent="claude", status=DelegateStatus.SUCCESS, reply="ok"))
        d = res.to_dict()
        self.assertIn("claude", d["successes"])
        self.assertEqual(d["success_agents"], ["claude"])


class TestHopLimit(unittest.TestCase):

    def test_ping_pong_detected(self):
        h = HopLimit()
        for a in ["claude", "codex", "claude", "codex"]:
            h.record(a, f"reply-{a}")
        self.assertTrue(h.ping_pong_detected)

    def test_stall_detected(self):
        # max_repeat=3：连续 4 次相同输出（允许 3 次重复，第 4 次停滞）
        h = HopLimit(max_repeat=3)
        for _ in range(4):
            h.record("claude", "same")
        self.assertTrue(h.is_stalled())


if __name__ == "__main__":
    unittest.main()

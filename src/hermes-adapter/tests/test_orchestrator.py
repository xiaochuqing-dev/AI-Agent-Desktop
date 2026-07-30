"""Unit tests for the Stage 2 orchestrator.

Uses a mock RelayClient (no real cc-connect) to verify: background async start,
pause/cancel control, DELEGATE/EXECUTION/DISCUSSION modes, the two-round rework
hard cap, and the controlled discussion-context construction (constraint #1).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

from plugins.multiagent.orchestrator import (
    Orchestrator, TaskRequest, MAX_REVIEW_REWORK, REPEAT_FUSE,
)
from plugins.multiagent.relay_client import HopGuard


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class FakeStore:
    """Minimal in-memory store stub for orchestrator tests."""
    def __init__(self):
        self.tasks = {}
        self.sessions = []
        self._counter = 0

    def create_task(self, *, chat_id, source, trigger_type, target_agents,
                    mode="DELEGATE", user_request="", reply_to_msg_id="", parent_task_id=None):
        self._counter += 1
        tid = f"task{self._counter:012d}"
        self.tasks[tid] = {
            "task_id": tid, "mode": mode, "status": "working",
            "review_rework_count": 0, "current_speaker": None,
            "target_agents": target_agents, "user_request": user_request,
        }
        return tid

    def update_task(self, task_id, **fields):
        if task_id in self.tasks:
            self.tasks[task_id].update(fields)

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def record_task_agent_session(self, task_id, agent_id, relay_session_key, turn):
        self.sessions.append((task_id, agent_id, relay_session_key, turn))


def make_orchestrator(store, mode, agents, user_request="测试任务",
                      replies=None, guard=None):
    """Build an orchestrator with a mocked RelayClient.send."""
    req = TaskRequest(
        chat_id="-100", user_id="u1", user_request=user_request,
        mode=mode, target_agents=agents, send_to_chat=lambda t: None,
    )
    orch = Orchestrator(store, req)
    # Replace the relay client created in start() with a mock-controlled one.
    replies = replies or ["reply"]
    call_state = {"i": 0}

    def fake_send(to_project, agent_id, message, turn=0, timeout=None):
        i = call_state["i"]
        call_state["i"] += 1
        reply = replies[i % len(replies)] if replies else "reply"
        # NOTE: do NOT append to orch._turns here - _delegate_once owns that.
        store.record_task_agent_session(orch._task_id or "x", agent_id, "relaykey", turn)
        return True, reply

    mock_relay = mock.MagicMock()
    mock_relay.send.side_effect = fake_send
    mock_relay.guard = guard or HopGuard()
    mock_relay.relay_session_key.return_value = "relay:hermes-task_x:telegram:-100"
    # Patch the relay after start() creates the real one.
    return orch, mock_relay


def start_with_mock_relay(orch, mock_relay):
    """start() creates a real RelayClient; swap it for the mock, then run."""
    # We can't easily intercept start(); instead patch RelayClient in the
    # orchestrator module before start by monkeypatching the class attribute.
    # Simpler: call start, then the thread uses self._relay which was set in
    # start().  So we patch before start via a wrapper.
    orig_init = orch.__class__.__init__

    def patched_start(self):
        # Replicate start() but inject mock relay.
        from plugins.multiagent.orchestrator import AGENT_PROJECTS
        self._task_id = self._store.create_task(
            chat_id=self._req.chat_id, source=self._req.user_id,
            trigger_type="orchestrator", target_agents=self._req.target_agents,
            mode=self._req.mode, user_request=self._req.user_request,
            reply_to_msg_id=self._req.reply_to_msg_id,
        )
        self._relay = mock_relay
        self._notify(f"task {self._task_id}")
        import threading
        self._thread = threading.Thread(target=self._run, name=f"ma-{self._task_id}", daemon=True)
        self._thread.start()
        return self._task_id

    orch.start = patched_start.__get__(orch)
    return orch.start()


# ---------------------------------------------------------------------------
# DELEGATE mode
# ---------------------------------------------------------------------------

def test_delegate_single_agent_completes():
    store = FakeStore()
    orch, mock_relay = make_orchestrator(store, "DELEGATE", ["claude"],
                                         replies=["Claude的分析结果"])
    start_with_mock_relay(orch, mock_relay)
    orch._thread.join(timeout=5)
    assert not orch.is_running
    task = store.get_task(orch.task_id)
    assert task["status"] == "DONE"
    assert mock_relay.send.call_count == 1


def test_delegate_two_agents_parallel_collect():
    store = FakeStore()
    orch, mock_relay = make_orchestrator(store, "DELEGATE", ["claude", "codex"],
                                         replies=["Claude说A", "Codex说B"])
    start_with_mock_relay(orch, mock_relay)
    orch._thread.join(timeout=5)
    assert mock_relay.send.call_count == 2
    task = store.get_task(orch.task_id)
    assert task["status"] == "DONE"


# ---------------------------------------------------------------------------
# Background async + control (correction #3)
# ---------------------------------------------------------------------------

def test_start_returns_immediately_nonblocking():
    store = FakeStore()
    orch, mock_relay = make_orchestrator(store, "DELEGATE", ["claude"],
                                         replies=["slow"])
    # Make relay slow so we can observe start() returning before completion.
    def slow_send(*a, **k):
        time.sleep(0.5)
        return True, "done"
    mock_relay.send.side_effect = slow_send
    start_with_mock_relay(orch, mock_relay)
    # start() returned a task_id and the thread is running, but not done yet.
    assert orch.task_id is not None
    assert orch.is_running
    orch._thread.join(timeout=5)


def test_cancel_stops_task():
    store = FakeStore()
    orch, mock_relay = make_orchestrator(store, "DISCUSSION", ["claude", "codex"],
                                         replies=["r1", "r2", "r3"])
    def slow_send(*a, **k):
        time.sleep(0.3)
        # _delegate_once appends the turn; we just delay and return.
        return True, "r"
    mock_relay.send.side_effect = slow_send
    start_with_mock_relay(orch, mock_relay)
    time.sleep(0.2)
    orch.cancel()
    orch._thread.join(timeout=5)
    task = store.get_task(orch.task_id)
    assert task["status"] == "canceled"


# ---------------------------------------------------------------------------
# EXECUTION: two-round rework hard cap (correction #5: same task_id)
# ---------------------------------------------------------------------------

def test_execution_rework_hard_cap():
    store = FakeStore()
    # Reviewer never says APPROVED -> forces max rework.
    orch, mock_relay = make_orchestrator(store, "EXECUTION", ["claude", "codex"],
                                         replies=["impl", "fix this", "impl2", "fix again",
                                                  "impl3", "fix more"])
    start_with_mock_relay(orch, mock_relay)
    orch._thread.join(timeout=5)
    task = store.get_task(orch.task_id)
    assert task["review_rework_count"] == MAX_REVIEW_REWORK
    assert task["status"] == "PAUSED"  # stopped auto-rework, awaiting user auth


def test_execution_approved_no_rework():
    store = FakeStore()
    orch, mock_relay = make_orchestrator(store, "EXECUTION", ["claude", "codex"],
                                         replies=["impl", "looks good APPROVED"])
    start_with_mock_relay(orch, mock_relay)
    orch._thread.join(timeout=5)
    task = store.get_task(orch.task_id)
    assert task["review_rework_count"] == 0
    assert task["status"] == "DONE"


def test_execution_rework_keeps_same_task_id():
    store = FakeStore()
    orch, mock_relay = make_orchestrator(store, "EXECUTION", ["claude", "codex"],
                                         replies=["impl", "fix", "impl2", "fix2", "impl3", "fix3"])
    start_with_mock_relay(orch, mock_relay)
    orch._thread.join(timeout=5)
    # All relay calls recorded against the SAME task_id (no new task per rework).
    assert all(s[0] == orch.task_id for s in store.sessions)


# ---------------------------------------------------------------------------
# DISCUSSION: dynamic convergence + fuses (constraint #6)
# ---------------------------------------------------------------------------

def test_discussion_converges_on_agreement():
    store = FakeStore()
    # After 3 turns, outputs have no disagreement markers -> convergence.
    orch, mock_relay = make_orchestrator(store, "DISCUSSION", ["claude", "codex"],
                                         replies=["我同意A", "我也同意A", "确认A"])
    start_with_mock_relay(orch, mock_relay)
    orch._thread.join(timeout=5)
    task = store.get_task(orch.task_id)
    assert task["status"] == "DONE"
    assert mock_relay.send.call_count >= 3  # at least 3 turns before convergence


def test_discussion_repeat_fuse_stops():
    store = FakeStore()
    # Guard reports consecutive repeats -> fuse trips.
    guard = HopGuard(consecutive_repeat=REPEAT_FUSE)
    orch, mock_relay = make_orchestrator(store, "DISCUSSION", ["claude", "codex"],
                                         replies=["same", "same", "same"], guard=guard)
    # Make guard update per call by cycling its value.
    call_n = {"i": 0}
    def send_and_bump(*a, **k):
        call_n["i"] += 1
        mock_relay.guard.consecutive_repeat = REPEAT_FUSE  # always at fuse
        # _delegate_once appends the turn; we just force the fuse.
        return True, "same"
    mock_relay.send.side_effect = send_and_bump
    start_with_mock_relay(orch, mock_relay)
    orch._thread.join(timeout=5)
    # Should stop quickly due to the repeat fuse, not run 40 hops.
    assert mock_relay.send.call_count < 5


# ---------------------------------------------------------------------------
# Controlled discussion context (constraint #1)
# ---------------------------------------------------------------------------

def test_discussion_context_includes_previous_original_output():
    store = FakeStore()
    orch, mock_relay = make_orchestrator(store, "DELEGATE", ["claude"])
    # Manually add a prior turn and build context.
    from plugins.multiagent.orchestrator import _TurnRecord
    orch._turns = [_TurnRecord(speaker="codex", output="Codex原始观点XYZ", turn=0)]
    ctx = orch._build_discussion_context("目标G", "议题D", "codex")
    assert "目标G" in ctx
    assert "议题D" in ctx
    assert "Codex原始观点XYZ" in ctx  # previous agent's ORIGINAL output, not a summary
    assert "上一位发言者 codex" in ctx


# ---------------------------------------------------------------------------
# Stage 2.5 (追加): smart concise summary (需求 §7-9)
# ---------------------------------------------------------------------------

def _orch_with_llm(store, llm_complete, detail_requested=False):
    """Build an orchestrator whose TaskRequest carries the given llm_complete."""
    req = TaskRequest(
        chat_id="-100", user_id="u1", user_request="分析一下",
        mode="DELEGATE", target_agents=["claude"], send_to_chat=lambda t: None,
        llm_complete=llm_complete, detail_requested=detail_requested,
    )
    return Orchestrator(store, req)


def _capturing_llm(captured):
    """An llm_complete that records the system prompt and returns a canned line."""
    def _complete(system, user):
        captured["system"] = system
        captured["user"] = user
        return "这是精炼总结。"
    return _complete


def test_summary_default_is_concise_not_rewrite():
    """需求 §7-8: default summary must instruct information-density compression,
    not a fixed-length rewrite.  The system prompt must carry the concise rules."""
    store = FakeStore()
    cap = {}
    orch = _orch_with_llm(store, _capturing_llm(cap), detail_requested=False)
    out = orch._summarise({"claude": "Claude的长篇分析" * 50})
    assert out == "这是精炼总结。"
    system = cap["system"]
    # Concise-mode markers (not the detailed-mode prompt).
    assert "精炼要点总结" in system
    assert "信息密度" in system or "信息量" in system
    assert "不要固定字数" in system
    # Must forbid mechanical rewrite of Worker output.
    assert "重写" in system


def test_summary_detail_requested_uses_expanded_prompt():
    """需求 §9: only when the user explicitly asked for detail does Hermes expand."""
    store = FakeStore()
    cap = {}
    orch = _orch_with_llm(store, _capturing_llm(cap), detail_requested=True)
    orch._summarise({"claude": "结果"})
    system = cap["system"]
    assert "详细总结" in system
    assert "完整" in system or "详细整合" in system
    # The concise-only rules must NOT be present in detailed mode.
    assert "精炼要点总结" not in system


def test_summary_no_llm_falls_back_labelled():
    """Without an LLM, never pass off raw agent text as a Hermes summary."""
    store = FakeStore()
    req = TaskRequest(
        chat_id="-100", user_id="u1", user_request="分析",
        mode="DELEGATE", target_agents=["claude"], send_to_chat=lambda t: None,
    )  # llm_complete defaults to None
    orch = Orchestrator(store, req)
    out = orch._summarise({"claude": "Claude原始输出"})
    assert "LLM 不可用" in out
    assert "Claude原始输出" in out


def test_summary_empty_results():
    store = FakeStore()
    orch = _orch_with_llm(store, _capturing_llm({}))
    assert orch._summarise({}) == "（无 agent 输出）"


# ---------------------------------------------------------------------------
# Stage 2.5 (追加): planned multi-step delegation (需求 §3/§5)
# ---------------------------------------------------------------------------

def test_planned_delegate_honours_explicit_agent_assignment():
    """需求 §5: A->codex, B->claude must NOT be swapped by the planner/orchestrator."""
    from plugins.multiagent._planner import SemanticPlan, PlanTask
    store = FakeStore()
    plan = SemanticPlan(
        action="DELEGATE", targets=["codex", "claude"],
        tasks=[
            PlanTask(label="A", goal="分析原因", agent="codex"),
            PlanTask(label="B", goal="查GitHub", agent="claude"),
        ],
        constraints="不要改代码", raw="A让Codex分析，B让Claude查",
    )
    req = TaskRequest(
        chat_id="-100", user_id="u1", user_request="A让Codex分析，B让Claude查",
        mode="DELEGATE", target_agents=["codex", "claude"],
        send_to_chat=lambda t: None, plan=plan,
    )
    orch = Orchestrator(store, req)
    # Capture which agent each relay call targeted.
    called_agents = []
    mock_relay = mock.MagicMock()
    mock_relay.guard = HopGuard()
    mock_relay.relay_session_key.return_value = "relaykey"

    def fake_send(to_project, agent_id, message, turn=0, timeout=None):
        called_agents.append(agent_id)
        store.record_task_agent_session(orch._task_id or "x", agent_id, "relaykey", turn)
        return True, f"{agent_id}的回复"
    mock_relay.send.side_effect = fake_send
    start_with_mock_relay(orch, mock_relay)
    orch._thread.join(timeout=5)
    # Explicit assignment preserved in order: codex first, then claude.
    assert called_agents == ["codex", "claude"]


def test_planned_delegate_carries_constraints_in_message():
    """The user constraint (不要改代码) must reach the agent's relay message."""
    from plugins.multiagent._planner import SemanticPlan, PlanTask
    store = FakeStore()
    plan = SemanticPlan(
        action="DELEGATE", targets=["claude"],
        tasks=[PlanTask(label="A", goal="实现功能X", agent="claude")],
        constraints="不要改代码，只给方案", raw="让Claude实现但不要改代码",
    )
    req = TaskRequest(
        chat_id="-100", user_id="u1", user_request="让Claude实现但不要改代码",
        mode="DELEGATE", target_agents=["claude"],
        send_to_chat=lambda t: None, plan=plan,
    )
    orch = Orchestrator(store, req)
    sent_messages = []
    mock_relay = mock.MagicMock()
    mock_relay.guard = HopGuard()
    mock_relay.relay_session_key.return_value = "relaykey"

    def fake_send(to_project, agent_id, message, turn=0, timeout=None):
        sent_messages.append(message)
        store.record_task_agent_session(orch._task_id or "x", agent_id, "relaykey", turn)
        return True, "回复"
    mock_relay.send.side_effect = fake_send
    start_with_mock_relay(orch, mock_relay)
    orch._thread.join(timeout=5)
    assert sent_messages, "relay send should have been called"
    assert "不要改代码" in sent_messages[0]
    assert "实现功能X" in sent_messages[0]


# ---------------------------------------------------------------------------
# 双 Agent 闭环（dual_agent 适配层）: 并行 / 顺序传结果 / 部分失败汇报
# ---------------------------------------------------------------------------

def _orch_with_plan(store, plan, mode="DELEGATE", targets=None):
    """构造带 plan 的 orchestrator + mock relay，返回 (orch, mock_relay, sent)。"""
    sent = {"messages": [], "agents": [], "results": {}}
    req = TaskRequest(
        chat_id="-100", user_id="u1",
        user_request=getattr(plan, "raw", "") or "双 Agent 任务",
        mode=mode, target_agents=targets or list(getattr(plan, "targets", []) or ["claude"]),
        send_to_chat=lambda t: None, plan=plan,
    )
    orch = Orchestrator(store, req)
    mock_relay = mock.MagicMock()
    mock_relay.guard = HopGuard()
    mock_relay.relay_session_key.return_value = "relaykey"

    def fake_send(to_project, agent_id, message, turn=0, timeout=None):
        sent["messages"].append((agent_id, message))
        sent["agents"].append(agent_id)
        store.record_task_agent_session(orch._task_id or "x", agent_id, "relaykey", turn)
        # 按预设返回成功/失败
        result = sent["results"].get(agent_id, ("ok", f"{agent_id}的回复"))
        kind, text = result
        return (kind == "ok"), text
    mock_relay.send.side_effect = fake_send
    return orch, mock_relay, sent


def test_dual_agent_parallel_both_agents_dispatched():
    """场景1: PARALLEL 模式下两个 Agent 都被派发（并行）。"""
    from plugins.multiagent._planner import SemanticPlan
    store = FakeStore()
    plan = SemanticPlan(action="PARALLEL", targets=["claude", "codex"],
                        raw="让两边分别独立分析")
    orch, mock_relay, sent = _orch_with_plan(store, plan)
    start_with_mock_relay(orch, mock_relay)
    orch._thread.join(timeout=5)
    # 两个 agent 都被派发
    assert set(sent["agents"]) == {"claude", "codex"}


def test_dual_agent_sequential_second_sees_first_output():
    """场景2: 顺序模式下第二步的消息含第一步的原始输出。"""
    from plugins.multiagent._planner import SemanticPlan, PlanTask
    store = FakeStore()
    # 第一步 claude 返回"方案A"，第二步 codex 应在消息里看到"方案A"
    plan = SemanticPlan(
        action="DELEGATE", targets=["claude", "codex"],
        tasks=[PlanTask(label="A", goal="给方案", agent="claude"),
               PlanTask(label="B", goal="审查", agent="codex")],
        raw="先让Claude给方案再让Codex审查",
    )
    orch, mock_relay, sent = _orch_with_plan(store, plan)
    # claude 成功返回"方案A"
    sent["results"]["claude"] = ("ok", "方案A")
    sent["results"]["codex"] = ("ok", "审查通过")
    start_with_mock_relay(orch, mock_relay)
    orch._thread.join(timeout=5)
    # 第一步消息不含前步输出
    first_msg = sent["messages"][0][1]
    assert "上一步的原始输出" not in first_msg
    # 第二步消息必须含第一步的原始输出"方案A"（非摘要）
    second_msg = sent["messages"][1][1]
    assert "方案A" in second_msg
    assert "上一步的原始输出" in second_msg


def test_dual_agent_partial_failure_reports_both():
    """场景3: 单边失败时总结必须汇报成功与失败两边（不丢成功结果）。"""
    from plugins.multiagent._planner import SemanticPlan
    store = FakeStore()
    plan = SemanticPlan(action="PARALLEL", targets=["claude", "codex"],
                        raw="让两边分析")
    orch, mock_relay, sent = _orch_with_plan(store, plan)
    # claude 成功，codex 失败
    sent["results"]["claude"] = ("ok", "实现没问题")
    sent["results"]["codex"] = ("fail", "codex 不可达")
    # 注入一个捕获总结的 LLM
    captured = {}
    def cap_llm(system, user):
        captured["user"] = user
        return "Claude成功，Codex失败建议重试"
    orch._req.llm_complete = cap_llm
    start_with_mock_relay(orch, mock_relay)
    orch._thread.join(timeout=5)
    # 总结 prompt 必须同时含成功结果与失败原因
    user_prompt = captured.get("user", "")
    assert "实现没问题" in user_prompt        # 成功结果不丢
    assert "codex 不可达" in user_prompt      # 失败原因进总结
    assert "codex" in user_prompt.lower()


def test_dual_agent_no_llm_digest_keeps_both():
    """无 LLM 时 digest 也要保留成败两边。"""
    from plugins.multiagent._planner import SemanticPlan
    store = FakeStore()
    plan = SemanticPlan(action="PARALLEL", targets=["claude", "codex"], raw="分析")
    orch, mock_relay, sent = _orch_with_plan(store, plan)
    sent["results"]["claude"] = ("ok", "Claude结论X")
    sent["results"]["codex"] = ("fail", "Codex掉线")
    # llm_complete 默认 None
    start_with_mock_relay(orch, mock_relay)
    orch._thread.join(timeout=5)
    # 找到 notify 发的汇总消息
    out_msgs = []
    orig_notify = orch._notify
    # _notify 在 run 线程里已调用过，我们改查 store 当前任务模式变化即可
    # 这里直接验证 _summarise_results 的输出
    orch2, _, _ = _orch_with_plan(store, plan)
    sent2 = {"messages": [], "agents": [], "results": {"claude": ("ok", "Claude结论X"), "codex": ("fail", "Codex掉线")}}
    # 用已加载的 dual_agent 直接验证 digest 路径
    from plugins.multiagent.orchestrator import _dual_agent_ready
    if not _dual_agent_ready:
        pytest.skip("dual_agent 未加载")
    # 重新跑一次拿 notify 输出
    notes = []
    req = TaskRequest(chat_id="-100", user_id="u1", user_request="分析",
                      mode="DELEGATE", target_agents=["claude", "codex"],
                      send_to_chat=lambda t: notes.append(t), plan=plan)
    orch3 = Orchestrator(store, req)
    mock_relay3 = mock.MagicMock()
    mock_relay3.guard = HopGuard()
    mock_relay3.relay_session_key.return_value = "relaykey"
    def fake3(to_project, agent_id, message, turn=0, timeout=None):
        kind, text = sent2["results"][agent_id]
        return (kind == "ok"), text
    mock_relay3.send.side_effect = fake3
    start_with_mock_relay(orch3, mock_relay3)
    orch3._thread.join(timeout=5)
    joined = "\n".join(notes)
    assert "Claude结论X" in joined
    assert "Codex掉线" in joined
    assert "LLM 不可用" in joined or "失败" in joined


def test_relay_client_uses_create_no_window():
    """A1 黑窗修复: relay_client.send 的 subprocess 必须带 CREATE_NO_WINDOW。"""
    import inspect
    from plugins.multiagent import relay_client
    src = inspect.getsource(relay_client)
    # 源码里必须出现 CREATE_NO_WINDOW 的数值 0x08000000
    assert "0x08000000" in src
    assert "creationflags" in src


def test_discussion_context_no_leakage_phrasing():
    """_build_discussion_context 的结尾不能含"回应分歧/同意/反驳"等
    会引导 Worker 公开说出"同意、无分歧"的措辞（指令泄漏根因）。"""
    store = FakeStore()
    orch = Orchestrator(store, TaskRequest(
        chat_id="-100", user_id="u1", user_request="讨论",
        mode="DISCUSSION", target_agents=["claude", "codex"],
        send_to_chat=lambda t: None,
    ))
    orch._task_id = "t1"
    ctx = orch._build_discussion_context("目标", "议题", None)
    # 不能含这些引导 Worker 说空话的词
    for bad in ("回应分歧", "补充新证据", "同意", "反驳"):
        assert bad not in ctx, f"discussion context 不应含引导词: {bad}"
    # 应含中性结论请求
    assert "结论" in ctx


def test_summarise_results_parallel_no_discussion_phrasing():
    """并行任务的总结 prompt 不应使用"共识/分歧/收敛/讨论"措辞。"""
    from plugins.multiagent._planner import SemanticPlan
    store = FakeStore()
    plan = SemanticPlan(action="PARALLEL", targets=["claude", "codex"], raw="查时间和CPU")
    captured = {}
    def cap(s, u):
        captured["system"] = s
        return "汇总"
    req = TaskRequest(chat_id="-100", user_id="u1", user_request="查时间和CPU",
                      mode="DELEGATE", target_agents=["claude", "codex"],
                      send_to_chat=lambda t: None, plan=plan, llm_complete=cap)
    orch = Orchestrator(store, req)
    # 直接调 _summarise_results，构造一个成功结果
    from plugins.multiagent.orchestrator import _dual_agent_ready
    if not _dual_agent_ready:
        pytest.skip("dual_agent 未加载")
    # 用 dual_agent 构造 AgentResults
    from dual_agent import AgentResults, DelegateResult, DelegateStatus
    res = AgentResults()
    res.add(DelegateResult(agent="claude", status=DelegateStatus.SUCCESS, reply="北京时间12点"))
    res.add(DelegateResult(agent="codex", status=DelegateStatus.SUCCESS, reply="CPU 30%"))
    orch._summarise_results(res)
    sys_prompt = captured.get("system", "")
    # 并行总结 prompt 必须明确"不是讨论"且禁止使用讨论措辞
    assert "不是讨论" in sys_prompt
    assert "不要使用" in sys_prompt and "共识" in sys_prompt  # 禁止这些词


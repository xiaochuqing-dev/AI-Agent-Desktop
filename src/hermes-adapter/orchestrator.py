"""Stage 2 orchestrator - Hermes' adaptive multi-agent scheduling.

Runs in a **background thread** (correction #3): ``_on_pre_dispatch`` only
creates the task and starts this thread, then returns immediately so the
Telegram gateway keeps accepting new messages (Reply corrections, @Hermes
pause/cancel) in real time.

Two orchestration modes (the user's "hybrid" decision), chosen per task:

  * manager-as-tools (DELEGATE / EXECUTION / REVIEW): Hermes delegates a
    bounded subtask via :class:`RelayClient`, gets the full reply back, and
    integrates it.  Hermes keeps control and owns the final summary - mirrors
    OpenAI ``Agent.as_tool()`` and LangGraph supervisor
    ``output_mode="last_message"``.

  * selector (DISCUSSION / RESEARCH): Hermes hosts a visible multi-turn
    discussion, each turn picking the next speaker via a Magentic-One-style
    Progress Ledger.  Convergence is *dynamic* (no fixed small round cap -
    constraint #6); the fuses only trip on anomalies (hop over max, ping-pong,
    consecutive repeats, stalls).

Visibility (correction #4): every agent formal output, Hermes stage summary
and mode/status change is pushed to Telegram via ``send_to_chat``.  We do NOT
fake real-time tool-call/progress streaming (cc-connect relay doesn't expose
internals); the Transcript (via the hook receiver) remains the audit log.

Controlled task discussion context (constraint #1): each relay Message carries
the task goal + Hermes' current issue/debate + the *previous agent's original
formal output* + relevant tool conclusions - never the whole Room Transcript,
never just a Hermes second-hand summary.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .relay_client import RelayClient
from .config import resolve_dual_agent_root

logger = logging.getLogger(__name__)

# Project name -> agent label mapping (matches cc-connect config.toml).
AGENT_PROJECTS = {"claude": "claude-expert", "codex": "codex-expert"}


# ── dual_agent 独立核心模块加载 ─────────────────────────────────────
# 双 Agent 闭环的纯逻辑（并行/顺序/聚合/部分失败/防重复）放在独立的
# ai-agent-collaboration/dual_agent 包里，不堆进 orchestrator.py。
# 路径解析集中在 config.resolve_dual_agent_root():
#   A. 环境变量 AI_AGENT_COLLAB_ROOT（开发/诊断覆盖）
#   B. multiagent.yaml 的 dual_agent_root（正式安装主来源）
#   C. 标准 junction 兼容回退
#   D. 全部无效则 fail-fast（不静默降级）。
# 不依赖 vbs/cmd/计划任务"恰好继承"环境变量。
_dual_agent_ready = False
try:
    _root = resolve_dual_agent_root()
    if _root and _root not in sys.path:
        sys.path.insert(0, _root)
    from dual_agent import (  # noqa: E402
        Delegator as _Delegator,
        DelegateResult as _DelegateResult,
        DelegateStatus as _DelegateStatus,
        AgentResults as _AgentResults,
        HopLimit as _HopLimit,
        ParallelTarget as _ParallelTarget,
        SequentialStep as _SequentialStep,
        run_parallel as _run_parallel,
        run_sequential as _run_sequential,
    )
    _dual_agent_ready = True
    logger.info("orchestrator: dual_agent 加载成功 root=%s", _root)
except Exception as _e:
    logger.error(
        "orchestrator: dual_agent 核心模块加载失败。"
        "并行/顺序任务将拒绝执行（不再静默降级到 legacy）。"
        " resolved_root=%r 错误=%s",
        _root, _e,
    )

# Fuse ceilings.  These are ANOMALY limits, not normal round caps (constraint
# #6).  Normal discussion converges dynamically; these only stop runaway loops.
MAX_HOPS_DISCUSSION = 40      # hard anomaly ceiling for open discussion
MAX_HOPS_DELEGATE = 6         # a single delegation should not ping-pong endlessly
MAX_STALLS = 5                # Magentic-One: consecutive no-progress -> replan/stop
MAX_REVIEW_REWORK = 2         # execution mode: at most 2 review->rework auto loops
REPEAT_FUSE = 3               # consecutive near-identical agent outputs -> stall


@dataclass
class TaskRequest:
    """A request to start an orchestrated task, parsed from the user message."""
    chat_id: str
    user_id: str
    user_request: str
    mode: str                      # DELEGATE | RESEARCH | DISCUSSION | EXECUTION
    target_agents: List[str]       # subset of [claude, codex]
    reply_to_msg_id: str = ""
    send_to_chat: Optional[Callable[[str], None]] = None  # TG visibility callback
    # Hermes host-owned LLM for genuine understanding/summarisation (NOT a
    # second-hand copy-paste).  Injected from __init__.py via ctx.llm.complete.
    # If None, falls back to a structured digest (clearly labelled as such).
    llm_complete: Optional[Callable[[str, str], str]] = None
    # Stage 2.5 (追加): the LLM semantic plan (action/tasks/constraints/...).
    # When present with multi-step tasks, _run_delegate honours the user's
    # explicit agent assignment + ordering (需求 §3/§5).  None for the legacy
    # keyword path.
    plan: Any = None
    # Stage 2.5 (追加): whether the user explicitly asked for a detailed
    # summary.  Default is a concise, information-density-driven summary (需求 §7-9).
    detail_requested: bool = False


@dataclass
class _TurnRecord:
    speaker: str            # claude | codex | hermes
    output: str
    turn: int


class Orchestrator:
    """Runs one orchestrated task to completion in a background thread.

    Lifecycle: ``start()`` spawns a daemon thread and returns immediately.
    ``pause()`` / ``cancel()`` flip the task status; the run loop checks
    between turns.  ``is_running`` tells the caller if the task is still live.
    """

    def __init__(self, store: Any, request: TaskRequest):
        self._store = store
        self._req = request
        self._task_id: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._relay = RelayClient(store, request.chat_id, "pending", )
        self._turns: List[_TurnRecord] = []
        self._error: Optional[str] = None

    # -- public lifecycle ----------------------------------------------

    def start(self) -> str:
        """Create the task and spawn the background run thread.

        Returns the task_id immediately (correction #3: non-blocking)."""
        self._task_id = self._store.create_task(
            chat_id=self._req.chat_id,
            source=self._req.user_id,
            trigger_type="orchestrator",
            target_agents=self._req.target_agents,
            mode=self._req.mode,
            user_request=self._req.user_request,
            reply_to_msg_id=self._req.reply_to_msg_id,
        )
        # Re-bind the relay client now that we have the real task_id.
        self._relay = RelayClient(self._store, self._req.chat_id, self._task_id)
        self._notify(f"🧩 已创建任务 {self._task_id}（模式：{self._req.mode}，参与者：{', '.join(self._req.target_agents)}）")
        self._thread = threading.Thread(
            target=self._run, name=f"ma-orch-{self._task_id}", daemon=True,
        )
        self._thread.start()
        logger.info("orchestrator: started task=%s mode=%s", self._task_id, self._req.mode)
        return self._task_id

    @property
    def task_id(self) -> Optional[str]:
        return self._task_id

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def pause(self) -> None:
        if self._task_id:
            self._pause.set()
            self._store.update_task(self._task_id, status="PAUSED")
            self._notify("⏸ 任务已暂停。@Hermes 继续可恢复。")

    def resume(self) -> None:
        if self._task_id:
            self._pause.clear()
            self._store.update_task(self._task_id, status="working")
            self._notify("▶ 任务已恢复。")

    def cancel(self) -> None:
        self._stop.set()
        self._pause.clear()  # unpause so the loop can exit
        if self._task_id:
            self._store.update_task(self._task_id, status="canceled")
            self._notify("🛑 任务已取消。")

    # -- internal helpers ----------------------------------------------

    def _notify(self, text: str) -> None:
        """Push a visibility message to the Telegram chat (correction #4)."""
        cb = self._req.send_to_chat
        if cb is None:
            logger.info("orchestrator (no-chat) %s: %s", self._task_id, text[:120])
            return
        try:
            cb(text)
        except Exception:
            logger.exception("orchestrator: send_to_chat failed")

    def _check_control(self) -> bool:
        """Return False if the task should stop (canceled).  Blocks while paused."""
        if self._stop.is_set():
            return False
        # Spin-wait on pause (cheap; turns are long).  Re-check cancel inside.
        while self._pause.is_set() and not self._stop.is_set():
            time.sleep(0.5)
        return not self._stop.is_set()

    def _build_discussion_context(self, goal: str, issue: str,
                                  prev_speaker: Optional[str]) -> str:
        """Controlled task discussion context (constraint #1).

        Contains: task goal + Hermes' current issue/debate + the previous
        agent's *original* formal output (not a Hermes summary) + an
        instruction.  Never the whole Transcript; never a second-hand digest.

        注意：这段 message 会经 relay（visibility=full）被 Worker Bot 原样发到
        群里当作它自己的公开发言。所以结尾指令必须中性，不能含"回应分歧/
        同意/反驳"等会引导 Worker 公开说出"同意、无分歧"这种空话的措辞。
        """
        parts: List[str] = []
        parts.append("【任务目标】" + goal)
        if issue:
            parts.append("【当前议题】" + issue)
        if self._turns:
            last = self._turns[-1]
            parts.append(f"【上一位发言者 {last.speaker} 的原始正式输出】\n{last.output[:3000]}")
        parts.append("请基于以上给出你的正式结论，直接输出结论内容，不要复述他人内容。")
        return "\n\n".join(parts)

    def _delegate_once(self, agent: str, message: str, turn: int) -> Optional[str]:
        """Manager-as-tools: relay to one agent, return its reply or None.

        The agent's formal output is posted to the group by the cc-connect
        relay itself (visibility=full -> targetEngine sends under the Worker
        Bot's own identity).  We do NOT re-forward it here (constraint #5: no
        duplicate display).  Hermes still receives the full reply via the relay
        RPC return value to continue orchestration + LLM summarisation.
        """
        project = AGENT_PROJECTS.get(agent)
        if not project:
            self._notify(f"⚠️ 未知 agent: {agent}")
            return None
        ok, reply = self._relay.send(project, agent, message, turn=turn)
        if not ok:
            self._notify(f"⚠️ {agent} 调用失败: {reply[:200]}")
            return None
        self._turns.append(_TurnRecord(speaker=agent, output=reply, turn=turn))
        # No _notify here: cc-connect relay visibility=full already posted the
        # Worker's formal output to the group under the Worker Bot's identity.
        return reply

    # -- main run loop --------------------------------------------------

    def _run(self) -> None:
        try:
            if self._req.mode == "DELEGATE":
                self._run_delegate()
            elif self._req.mode == "EXECUTION":
                self._run_execution()
            elif self._req.mode in ("DISCUSSION", "RESEARCH"):
                self._run_discussion()
            else:
                self._notify(f"⚠️ 不支持的模式: {self._req.mode}")
                self._store.update_task(self._task_id, status="failed")
                return
            if not self._stop.is_set():
                # Don't clobber a PAUSED/failed status set by a sub-mode
                # (e.g. EXECUTION pauses when the rework cap is hit).
                cur = self._store.get_task(self._task_id) or {}
                if cur.get("status", "working") == "working":
                    self._store.update_task(self._task_id, status="DONE")
                    self._notify(f"✅ 任务 {self._task_id} 完成。")
        except Exception as exc:
            self._error = str(exc)
            logger.exception("orchestrator: task %s failed", self._task_id)
            self._store.update_task(self._task_id, status="failed")
            self._notify(f"❌ 任务异常: {exc[:200]}")

    # -- mode: DELEGATE (manager-as-tools) --------------------------------
    # 双 Agent 闭环：并行/顺序/部分失败逻辑在独立 dual_agent 包里。
    # 本方法只做适配：把 plan 转成 dual_agent 的 targets/steps，注入 relay
    # 委派函数，调 dual_agent 执行，结果交回 _summarise。不再内联业务逻辑。

    def _make_delegator(self) -> Callable:
        """把 relay_client.send 包成 dual_agent 的 Delegator（callable）。
        返回 (agent, message, turn) -> DelegateResult。"""
        def _delegate(agent: str, message: str, turn: int = 0, **kw) -> Any:
            if not self._check_control():
                return _DelegateResult(agent=agent, status=_DelegateStatus.FAILED,
                                       error="任务已取消", turn=turn)
            project = AGENT_PROJECTS.get(agent)
            if not project:
                return _DelegateResult(agent=agent, status=_DelegateStatus.FAILED,
                                       error=f"未知 agent: {agent}", turn=turn)
            self._store.update_task(self._task_id, mode="DELEGATE", current_speaker=agent)
            ok, reply = self._relay.send(project, agent, message, turn=turn)
            if not ok:
                # relay 失败：区分超时与一般失败（reply 文本含 timeout 字样）
                r_text = reply or ""
                if "timeout" in r_text.lower():
                    return _DelegateResult(agent=agent, status=_DelegateStatus.TIMEOUT,
                                           error=r_text[:300], turn=turn)
                return _DelegateResult(agent=agent, status=_DelegateStatus.FAILED,
                                       error=r_text[:300], turn=turn)
            self._turns.append(_TurnRecord(speaker=agent, output=reply, turn=turn))
            return _DelegateResult(agent=agent, status=_DelegateStatus.SUCCESS,
                                   reply=reply, turn=turn)
        return _delegate

    def _run_delegate(self) -> None:
        """双 Agent 闭环入口。按 plan.action 决定并行/顺序，调 dual_agent 执行。"""
        plan = getattr(self._req, "plan", None)
        action = getattr(plan, "action", "") if plan is not None else ""
        tasks = getattr(plan, "tasks", None) if plan is not None else None
        targets = self._req.target_agents or ["claude"]

        # 判断是否为需要 dual_agent 的多 Agent 编排场景
        needs_dual_agent = (
            (action == "PARALLEL" and len(targets) > 1)
            or bool(tasks)
            or (len(targets) > 1)
        )

        if not _dual_agent_ready:
            if needs_dual_agent:
                # 并行/顺序/多 Agent 场景必须 dual_agent，禁止静默降级到 legacy
                self._store.update_task(self._task_id, status="failed")
                self._notify(
                    "⚠️ 多 Agent 编排能力未就绪（dual_agent 核心模块未加载），"
                    "本次并行/顺序任务已取消，未派发任何 Worker。"
                    "请联系维护者检查 dual_agent_root 配置。"
                )
                logger.error(
                    "orchestrator: 拒绝静默降级。任务 %s 需 dual_agent 但未加载 "
                    "(action=%s targets=%s tasks=%s)",
                    self._task_id, action, targets, bool(tasks),
                )
                return
            # 单 Agent 单步:legacy 串行委派等价于普通委派，安全允许
            self._run_delegate_legacy()
            return
        constraints = getattr(plan, "constraints", "") if plan is not None else ""

        hop = _HopLimit(max_hops=MAX_HOPS_DELEGATE * 2)
        delegator = self._make_delegator()

        # 并行：只有 PARALLEL action 才走并行分支。
        # 注意：DELEGATE + 多 agent + 无 tasks 不应走并行（那是“各做整个请求”，
        # 会把用户对其他 agent 的指令传给某个 agent，导致它公开当主持人）。
        # DELEGATE 多 agent 无 tasks 时走顺序退化（各做自己一份，互不串）。
        is_parallel = action == "PARALLEL"
        if is_parallel and len(targets) > 1:
            self._store.update_task(self._task_id, mode="DELEGATE")
            # 优先用 plan.tasks 的 goal（每个 agent 独立目标，不含跨 agent 指令）；
            # 无 tasks 时退化成各做整个用户请求（但只给该 agent 的副本）。
            if tasks:
                ptg = []
                for t in tasks:
                    a = (getattr(t, "agent", "") or "").lower()
                    if a not in ("claude", "codex"):
                        a = targets[0] if targets else "claude"
                    ptg.append(_ParallelTarget(agent=a, message=self._build_parallel_message(a, constraints, getattr(t, "goal", ""))))
                # targets 里可能还有没在 tasks 的 agent，补上（用整个请求）
                for a in targets:
                    if a not in [getattr(t, "agent", "").lower() for t in tasks]:
                        ptg.append(_ParallelTarget(agent=a, message=self._build_parallel_message(a, constraints, "")))
            else:
                ptg = [_ParallelTarget(agent=a, message=self._build_parallel_message(a, constraints, ""))
                       for a in targets]
            results = _run_parallel(ptg, delegator, hop)
        elif tasks:
            # 顺序多步：按 plan.tasks 逐步执行，前步输出注入后步（场景2）
            self._store.update_task(self._task_id, mode="DELEGATE")
            steps = self._plan_tasks_to_steps(tasks, targets)
            results = _run_sequential(steps, delegator, hop, self._build_step_message)
        elif len(targets) > 1:
            # DELEGATE 多 agent 无 tasks：planner 没切分子任务，各做整个请求的独立部分。
            # 走并行（互不阻塞），消息用防主持措辞（只做自己的，不调度他人）。
            self._store.update_task(self._task_id, mode="DELEGATE")
            ptg = [_ParallelTarget(agent=a, message=self._build_parallel_message(a, constraints, ""))
                   for a in targets]
            results = _run_parallel(ptg, delegator, hop)
        else:
            # 单 agent 退化：当成顺序单步
            self._store.update_task(self._task_id, mode="DELEGATE")
            steps = [_SequentialStep(agent=targets[0], goal=self._req.user_request)]
            results = _run_sequential(steps, delegator, hop, self._build_step_message)

        # 记录跳数到 relay guard（审计一致性）
        self._sync_guard(hop)
        # 交回 Hermes 总结
        self._store.update_task(self._task_id, current_speaker="hermes")
        summary = self._summarise_results(results)
        self._notify(f"📝 Hermes 汇总：\n{summary}")

    def _build_parallel_message(self, agent: str, constraints: str, goal: str = "") -> str:
        """并行模式下给某 agent 的消息：该 agent 自己的目标 + 约束。
        有 plan.tasks 的 goal 时只给该 goal（不含跨 agent 指令）；无则退化用整个请求。
        关键：消息会经 relay 被 Worker Bot 原样发群，所以必须明确告诉它“只做你的部分，
        不要调度或提及其他 Agent”，否则它会公开当主持人（说“请Codex审查”等）。"""
        if goal:
            body = goal
        else:
            body = self._req.user_request[:2000]
        parts = [f"【你的任务】{body}"]
        if constraints:
            parts.append(f"【用户约束】{constraints}")
        parts.append("你只需完成分配给你的这一部分。直接输出你的结论。"
                     "不要提及、调度或转交给其他 Agent，不要说“请某某审查/继续”。")
        return "\n\n".join(parts)

    def _build_step_message(self, agent: str, goal: str, prior_output: Optional[str]) -> str:
        """顺序模式下当前步的消息：目标 + 约束 + 前步原始输出（非摘要）。"""
        parts = [f"【这一步的目标】{goal}"]
        constraints = getattr(getattr(self._req, "plan", None), "constraints", "") or ""
        if constraints:
            parts.append(f"【用户约束】{constraints}")
        if prior_output:
            # 注入前一步的原始正式输出（需求 §B2：第二个 Agent 必须真正看到第一个的结果）
            parts.append(f"【上一步的原始输出】\n{prior_output[:3000]}")
        parts.append("请基于以上给出你的正式结论。")
        return "\n\n".join(parts)

    def _plan_tasks_to_steps(self, tasks: List[Any], default_targets: List[str]) -> List[Any]:
        """把 plan.tasks 转成 dual_agent 的 SequentialStep 列表。
        用户显式指定的 agent 与顺序严格服从（需求 §5）。"""
        steps = []
        for t in tasks:
            agent = (getattr(t, "agent", "") or "").lower()
            if agent == "both":
                # "both" -> 拆成两步（claude 在前 codex 在后），各自独立
                for a in ("claude", "codex"):
                    steps.append(_SequentialStep(agent=a, goal=getattr(t, "goal", ""),
                                                 label=getattr(t, "label", "") or a))
            else:
                if agent not in ("claude", "codex"):
                    agent = (default_targets or ["claude"])[0]
                steps.append(_SequentialStep(agent=agent, goal=getattr(t, "goal", ""),
                                             label=getattr(t, "label", "") or agent))
        return steps

    def _sync_guard(self, hop: Any) -> None:
        """把 dual_agent 的跳数镜像到 relay_client 的 HopGuard（审计一致）。"""
        try:
            with self._relay._lock:
                self._relay._guard.hop_count = max(self._relay._guard.hop_count, hop.hop_count)
        except Exception:
            pass

    def _run_delegate_legacy(self) -> None:
        """降级路径：dual_agent 不可用时，串行委派每个 agent（无并行/顺序传结果）。"""
        agents = self._req.target_agents or ["claude"]
        turn = 0
        results: Dict[str, str] = {}
        for agent in agents:
            if not self._check_control():
                return
            self._store.update_task(self._task_id, mode="DELEGATE", current_speaker=agent)
            ctx = self._build_discussion_context(self._req.user_request, "", None)
            reply = self._delegate_once(agent, ctx, turn)
            if reply is not None:
                results[agent] = reply
            turn += 1
            if self._relay.guard.would_exceed_max_hops(MAX_HOPS_DELEGATE):
                self._notify("⚠️ 委派跳数异常，停止（保险丝）。")
                return
        self._store.update_task(self._task_id, current_speaker="hermes")
        summary = self._summarise(results)
        self._notify(f"📝 Hermes 汇总：\n{summary}")

    # -- mode: EXECUTION (implement -> review -> <=2 rework) -----------

    def _run_execution(self) -> None:
        """Implement with the first agent, review with the other, at most
        MAX_REVIEW_REWORK auto rework loops (constraint: two-round hard cap)."""
        agents = self._req.target_agents or ["claude"]
        implementer = agents[0]
        reviewer = agents[1] if len(agents) > 1 else agents[0]
        turn = 0
        # 1. Implement
        if not self._check_control():
            return
        self._store.update_task(self._task_id, mode="EXECUTION", current_speaker=implementer)
        impl = self._delegate_once(implementer, self._req.user_request, turn)
        turn += 1
        if impl is None:
            return
        # 2. Review -> rework loop (same task_id, increment counter - correction #5)
        while True:
            if not self._check_control():
                return
            rework_count = self._store.get_task(self._task_id)["review_rework_count"]
            if rework_count >= MAX_REVIEW_REWORK:
                self._notify(f"⚠️ 已达 {MAX_REVIEW_REWORK} 轮自动返工上限。剩余问题需人工授权继续。")
                self._store.update_task(self._task_id, mode="REVIEW", status="PAUSED")
                return  # stop auto-rework; user may authorise more
            self._store.update_task(self._task_id, mode="REVIEW", current_speaker=reviewer)
            # 注意：review_msg 会经 relay（visibility=full）被 reviewer Bot 原样发到
            # 群里当作它的公开发言。所以不能含"请审查/请指出问题"这种指令性
            # 措辞（否则 Worker 会在群里复读"请审查..."）。改成中性的材料呈现，
            # 让 reviewer 自然输出审查结论。
            review_msg = (
                self._build_discussion_context(
                    self._req.user_request, "对以下实现做审查", None,
                )
                + f"\n\n【待审查的实现】\n{impl[:3000]}"
            )
            review = self._delegate_once(reviewer, review_msg, turn)
            turn += 1
            if review is None:
                return
            if "APPROVED" in review.upper():
                self._notify("✅ Review 通过。")
                self._store.update_task(self._task_id, current_speaker="hermes")
                self._notify(f"📝 Hermes 汇总：\n{self._summarise({implementer: impl, reviewer: review})}")
                return
            # Rework: increment counter, re-implement with review feedback.
            self._store.update_task(self._task_id, review_rework_count=rework_count + 1,
                                    mode="EXECUTION", current_speaker=implementer)
            self._notify(f"🔧 第 {rework_count + 1} 轮返工（上限 {MAX_REVIEW_REWORK}）...")
            rework_msg = (
                self._build_discussion_context(
                    self._req.user_request, "参考审查意见重新实现", None,
                )
                + f"\n\n【审查意见】\n{review[:3000]}"
            )
            impl = self._delegate_once(implementer, rework_msg, turn)
            turn += 1
            if impl is None:
                return

    # -- mode: DISCUSSION / RESEARCH (selector, dynamic convergence) ---

    def _run_discussion(self) -> None:
        """Host a visible multi-turn discussion with dynamic convergence.

        No fixed small round cap (constraint #6): the fuses (hop over max,
        ping-pong, consecutive repeats, stalls) only trip on anomalies.
        Convergence is detected by the Progress Ledger each turn.
        """
        agents = self._req.target_agents or ["claude", "codex"]
        turn = 0
        n_stalls = 0
        while True:
            if not self._check_control():
                return
            guard = self._relay.guard
            # --- Fuses (anomaly-only, never a normal round cap) ---
            if guard.would_exceed_max_hops(MAX_HOPS_DISCUSSION):
                self._notify("⚠️ 讨论跳数异常，保险丝触发（停止）。")
                return
            if guard.ping_pong_detected:
                self._notify("⚠️ 检测到 ping-pong，Hermes 介入引导。")
                n_stalls = min(n_stalls + 1, MAX_STALLS)
            if guard.consecutive_repeat >= REPEAT_FUSE:
                self._notify("⚠️ 连续重复输出，讨论已无新增信息，收敛。")
                break
            if n_stalls >= MAX_STALLS:
                self._notify("⚠️ 多轮无进展，Hermes 收束讨论。")
                break
            # --- Selector: pick the next speaker (Hermes decides). ---
            speaker = self._select_speaker(agents, turn)
            self._store.update_task(self._task_id, mode=self._req.mode,
                                    current_speaker=speaker)
            prev_speaker = self._turns[-1].speaker if self._turns else None
            issue = self._derive_issue()
            ctx = self._build_discussion_context(self._req.user_request, issue, prev_speaker)
            reply = self._delegate_once(speaker, ctx, turn)
            turn += 1
            if reply is None:
                return
            # --- Progress Ledger: dynamic convergence check ---
            if self._is_converged():
                self._notify("✅ 讨论基本收敛。")
                break
            # Decay stalls when real progress is made.
            if not guard.ping_pong_detected and guard.consecutive_repeat == 0:
                n_stalls = max(0, n_stalls - 1)
        # Hermes final summary.
        self._store.update_task(self._task_id, current_speaker="hermes")
        summary = self._summarise({t.speaker: t.output for t in self._turns})
        self._notify(f"📝 Hermes 最终汇总：\n{summary}")

    # -- selector + convergence (overridable for testing) --------------

    def _select_speaker(self, agents: List[str], turn: int) -> str:
        """Pick the next speaker.  Round-robin with a no-immediate-repeat rule;
        Hermes may override based on the Progress Ledger.  This is a pragmatic
        selector (avoids an extra LLM call per turn) - the convergence check
        below carries the real stopping logic."""
        if len(agents) == 1:
            return agents[0]
        last = self._turns[-1].speaker if self._turns else None
        # Pick the next agent that isn't the immediate previous speaker.
        for a in agents:
            if a != last:
                return a
        return agents[turn % len(agents)]

    def _derive_issue(self) -> str:
        """Best-effort: summarise the current point of contention from turns."""
        if len(self._turns) < 2:
            return ""
        return "请回应上一位发言者的观点：同意/反驳/补充，并给出理由或证据。"

    def _is_converged(self) -> bool:
        """Progress Ledger convergence signal.

        A real Magentic-One ledger asks the LLM for is_request_satisfied each
        turn.  To avoid an extra model call per turn here, we use a lightweight
        heuristic: convergence when agents stop disagreeing (no explicit
        disagreement markers in the last 2 turns) AND at least 3 turns have
        happened.  The orchestrator can be subclassed to plug in a real LLM
        ledger.  The fuses above still bound anomalies regardless.
        """
        if len(self._turns) < 3:
            return False
        recent = self._turns[-2:]
        markers = ("不同意", "不对", "反驳", "不赞同", "问题", "错误", "wrong", "disagree")
        return not any(m in t.output for t in recent for m in markers)

    # -- summarise (Hermes owns the final output) ----------------------

    def _summarise_results(self, results: Any) -> str:
        """把 dual_agent 的 AgentResults 交给 Hermes LLM 总结（需求 §B3）。

        与 _summarise 的区别：明确汇报每个 Agent 的成败、已取得的结果、
        是否建议重试，不丢任何一边。失败/超时原因进总结 prompt。
        """
        if not _dual_agent_ready or results is None:
            return "（双 Agent 模块不可用，无结果）"
        success = results.success_replies()   # {agent: reply}
        failures = results.failure_summary()  # ["codex 失败：...", "claude 超时(...)"]
        stopped = results.stopped_reason

        # 无 LLM 时回退标注式 digest（不伪装成 Hermes 判断）
        if self._req.llm_complete is None:
            return self._results_digest(results, success, failures, stopped)

        # 构造给 LLM 的成败上下文
        parts = []
        for agent, out in success.items():
            parts.append(f"【{agent} 的正式输出（成功）】\n{out[:3000]}")
        if failures:
            parts.append("【失败/超时的 Agent】\n" + "\n".join(failures))
        if stopped:
            parts.append(f"【任务非正常终止】{stopped}")
        agent_block = "\n\n".join(parts) if parts else "（无 Agent 输出）"

        # 按 plan.action 区分总结措辞：并行/顺序不提"共识/分歧/收敛"，
        # 只有用户明确要求讨论（DISCUSS）才允许这些词。避免把独立任务误述为讨论。
        action = getattr(getattr(self._req, "plan", None), "action", "")
        is_discuss = action == "DISCUSS"

        if self._req.detail_requested:
            if is_discuss:
                system = (
                    "你是 Hermes，多 Agent 协作的主持人。用户已明确要求详细总结，且这是讨论场景。"
                    "请结合用户原始请求，对各 Agent 的输出做完整、有条理的整合："
                    "覆盖主要结论、过程要点、分歧与风险、是否达成共识、下一步。"
                    "若有 Agent 失败或超时，明确说明是谁、什么原因、是否建议重试。用中文。"
                )
            else:
                system = (
                    "你是 Hermes，多 Agent 协作的主持人。用户已明确要求详细总结。"
                    "这是独立并行或顺序任务，不是讨论。请分别汇总各 Agent 的结论："
                    "覆盖主要结论、过程要点、风险、下一步。可以较长，但仍要条理清晰。"
                    "不要使用“共识、分歧、收敛、讨论”等词，因为用户没有要求讨论。"
                    "若有 Agent 失败或超时，明确说明是谁、什么原因、是否建议重试。用中文。"
                )
        else:
            if is_discuss:
                system = (
                    "你是 Hermes，多 Agent 协作的主持人。这是讨论场景，做【精炼要点总结】。\n"
                    "规则：\n"
                    "1. 只保留：核心结论、关键发现、重要风险或分歧、是否达成共识、必要的下一步。\n"
                    "2. 删除：推理铺垫、工具过程、重复解释、同义复述、对原文的大段改写。\n"
                    "3. 长度由实际有效信息量自然决定，不固定字数。Worker 只说一句，你也只回一句。\n"
                    "4. 若有 Agent 失败/超时，必须明确说明是谁、原因、是否建议重试，不能漏报。\n"
                    "5. 用中文，直接输出总结，不加前缀套话。"
                )
            else:
                system = (
                    "你是 Hermes，多 Agent 协作的主持人。这是独立并行或顺序任务，不是讨论。做【精炼要点总结】。\n"
                    "规则：\n"
                    "1. 只保留：各 Agent 的核心结论、关键发现、重要风险、必要的下一步。\n"
                    "2. 删除：推理铺垫、工具过程、重复解释、同义复述、对原文的大段改写。\n"
                    "3. 长度由实际有效信息量自然决定，不固定字数。Worker 只说一句，你也只回一句。\n"
                    "4. 不要使用“共识、分歧、收敛、讨论”等词，因为这不是讨论任务。\n"
                    "5. 若有 Agent 失败/超时，必须明确说明是谁、原因、是否建议重试，不能漏报。\n"
                    "6. 用中文，直接输出总结，不加前缀套话。"
                )
        user = (
            f"【用户原始请求】\n{self._req.user_request[:2000]}\n\n"
            f"{agent_block}\n\n请给出总结。"
            f"{'已建议重试失败的 Agent。' if results.recommend_retry() else ''}"
        )
        try:
            summary = self._req.llm_complete(system, user)
            if summary and summary.strip():
                return summary.strip()
        except Exception:
            logger.exception("orchestrator: llm_complete failed, falling back to digest")
        return self._results_digest(results, success, failures, stopped)

    def _results_digest(self, results: Any, success: Dict[str, str],
                        failures: List[str], stopped: str) -> str:
        """无 LLM 时的标注式 digest（明标非 Hermes 判断，不丢结果）。"""
        lines = ["（LLM 不可用，以下为 Agent 原始结果未整合）"]
        for agent, out in success.items():
            lines.append(f"【{agent} 成功】{out[:800]}")
        if failures:
            lines.append("【失败/超时】" + "；".join(failures))
        if stopped:
            lines.append(f"【终止原因】{stopped}")
        if results.recommend_retry():
            lines.append("（建议重试失败的 Agent）")
        return "\n".join(lines)

    def _summarise(self, results: Dict[str, str]) -> str:
        """Hermes genuinely understands and integrates the agent outputs.

        Stage 2.5 (追加, 需求 §7-9): DEFAULT is an information-density-driven
        *concise* summary - keep only 核心结论/关键发现/重要风险或分歧/必要下一步;
        drop 推理铺垫/工具过程/重复/同义复述/对原文的大段改写.  Length is decided by
        real information density, NOT a fixed word count or compression ratio.
        If a Worker said one simple line, Hermes may say just that (or even
        "任务完成").  Only when the user explicitly asked for a detailed summary
        (detail_requested) does Hermes expand.

        Uses the host-owned LLM (ctx.llm).  If no LLM is wired (trust policy /
        tests), falls back to a clearly labelled digest so we never silently
        pass off raw agent text as a Hermes summary.
        """
        if not results:
            return "（无 agent 输出）"
        # Build the agent-outputs block for the model.
        parts = []
        for agent, out in results.items():
            parts.append(f"【{agent} 的正式输出】\n{out[:3000]}")
        agent_block = "\n\n".join(parts)

        if self._req.llm_complete is not None:
            if self._req.detail_requested:
                system = (
                    "你是 Hermes，多 Agent 协作的主持人。用户已明确要求详细总结。"
                    "请结合用户原始请求，对各 Agent 的输出做完整、有条理的整合："
                    "覆盖主要结论、过程要点、分歧与风险、下一步。可以较长，但仍要条理清晰，"
                    "不要无意义复述原文。用中文。"
                )
                user = (
                    f"【用户原始请求】\n{self._req.user_request[:2000]}\n\n"
                    f"{agent_block}\n\n"
                    "请给出详细整合总结。"
                )
            else:
                system = (
                    "你是 Hermes，多 Agent 协作的主持人。默认做【精炼要点总结】，不是改写复述。\n"
                    "规则：\n"
                    "1. 只保留：核心结论、关键发现、重要风险或分歧（如果有）、必要的下一步建议（如果确实需要）。\n"
                    "2. 删除：推理铺垫、工具过程、重复解释、同义复述、不影响结论的细节、对 Worker 原文的大段重新改写。\n"
                    "3. 长度由实际有效信息量自然决定：不要固定字数、不要固定压缩比。\n"
                    "   - 若 Worker 只给了一句简单结论（如“测试通过，未发现问题”），你也只回一句精炼结论，甚至“任务完成。”即可。\n"
                    "   - 若确实有多个彼此独立且都重要的结论，可以自然更长，但每句都要有信息价值。\n"
                    "4. 绝不把 Worker 的长输出换种说法重写一遍——那不叫总结，是语义重写。你要做信息压缩。\n"
                    "5. 用中文。直接输出总结内容，不要加“总结如下”之类的前缀套话。"
                )
                user = (
                    f"【用户原始请求】\n{self._req.user_request[:2000]}\n\n"
                    f"{agent_block}\n\n"
                    "请给出精炼要点总结。"
                )
            try:
                summary = self._req.llm_complete(system, user)
                if summary and summary.strip():
                    return summary.strip()
                logger.warning("orchestrator: llm_complete returned empty, falling back")
            except Exception:
                logger.exception("orchestrator: llm_complete failed, falling back to digest")
        # Fallback (clearly labelled - never presented as a Hermes judgement).
        if len(results) == 1:
            agent, out = next(iter(results.items()))
            return f"（LLM 不可用，{agent} 原始输出）\n{out[:1500]}"
        return (
            "（LLM 不可用，以下为各 Agent 输出未整合）\n\n"
            + "\n\n".join(f"【{a}】{o[:800]}" for a, o in results.items())
        )

"""multiagent plugin - Stage 1.5 group governance for the 3-bot Telegram topology.

Wires:
  1. ``pre_gateway_dispatch`` hook - the Hermes-side *hard gate*.  Runs BEFORE
     auth/agent dispatch.  Implements the unified routing protocol
     (policy.decide), records to the shared Transcript, enforces idempotency
     and anti-loop, and injects reference context for cross-agent replies.
  2. Slash commands (``/ma*`` namespace) - /mashare /maforget /mashared
     /maroute /macontext /macancel /manew.  Namespaced to avoid colliding
     with cc-connect's built-in commands (/new /status /stop ...) which, in a
     bare-command broadcast, would otherwise trigger all 3 bots.
  3. HTTP hook receiver (localhost) - accepts cc-connect ``message.received``
     and ``message.sent_delivered`` POSTs and writes them to the shared
     Transcript, so Claude/Codex inbound + outbound messages are recorded.

See docs/reports/stage-1.5-...-report.md for the full design + honest
✅/🟡/⏳ capability marking.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple

# 探针2：__init__ import 时写标记，确认 gateway 加载的是这个文件。
# register() 也会触发，但 import 阶段更早，能区分"加载了但 register 没跑"。
try:
    with open(r"C:\Users\<WINDOWS_USER>\AppData\Local\hermes\_init_probe.txt", "w", encoding="utf-8") as _pf:
        _pf.write("multiagent __init__.py loaded from " + __file__ + "\n")
except Exception:
    pass

from . import config as ma_config
from . import policy as ma_policy
from .store import get_store

logger = logging.getLogger(__name__)

# Module-level singletons, lazily initialised in register().
_cfg: Optional[ma_config.MultiAgentConfig] = None
_cfg_lock = threading.Lock()
_receiver_started = False
_receiver_lock = threading.Lock()

# Stage 2: host-owned LLM facade (ctx.llm) for genuine Hermes understanding.
# Lazily captured in register(); None if the plugin isn't trusted to use LLM.
_llm_facade: Any = None

# Stage 2: active orchestrators keyed by task_id.  Tracks running background
# tasks so _on_pre_dispatch can route user interventions (Reply-to-task,
# @Hermes pause/cancel, multi-task clarification - constraint #5).
_active_orchs: Dict[str, Any] = {}
_active_orchs_lock = threading.Lock()


def _register_orch(task_id: str, orch: Any) -> None:
    with _active_orchs_lock:
        _active_orchs[task_id] = orch


def _unregister_orch(task_id: str) -> None:
    with _active_orchs_lock:
        _active_orchs.pop(task_id, None)


def _active_orchs_for_chat(chat_id: str) -> List[Any]:
    """Return live orchestrators whose task is in this chat (for multi-task
    clarification).  Cleans up finished entries as a side effect."""
    from .store import get_store as _gs
    store = _gs()
    out = []
    with _active_orchs_lock:
        for tid, orch in list(_active_orchs.items()):
            if not orch.is_running:
                _active_orchs.pop(tid, None)
                continue
            t = store.get_task(tid)
            if t and f":{chat_id}:" in (t.get("idempotency_key") or ""):
                out.append(orch)
    return out


def _get_cfg() -> ma_config.MultiAgentConfig:
    global _cfg
    if _cfg is not None:
        return _cfg
    with _cfg_lock:
        if _cfg is None:
            _cfg = ma_config.load_config()
            if not _cfg.enabled:
                logger.warning("multiagent: plugin disabled (config missing or malformed)")
        return _cfg


def _ensure_receiver_started() -> None:
    """Start the localhost HTTP receiver once, on first hook fire."""
    global _receiver_started
    if _receiver_started:
        return
    with _receiver_lock:
        if _receiver_started:
            return
        cfg = _get_cfg()
        if not cfg.enabled or not cfg.receiver_secret or cfg.receiver_secret == "CHANGE_ME_TO_A_LONG_RANDOM_SECRET":
            logger.warning("multiagent: hook receiver NOT started (disabled or secret unset)")
            return
        try:
            from .webhook_receiver import start_receiver
            start_receiver(cfg, get_store())
            _receiver_started = True
            logger.info("multiagent: hook receiver started on %s:%d", cfg.receiver_host, cfg.receiver_port)
        except Exception:
            logger.exception("multiagent: failed to start hook receiver")


def _build_route_input(event: Any) -> ma_policy.RouteInput:
    """Snapshot policy-relevant fields from a Hermes MessageEvent."""
    source = getattr(event, "source", None)
    chat_id = getattr(source, "chat_id", "") or ""
    chat_type = getattr(source, "chat_type", "dm") or "dm"
    thread_id = getattr(source, "thread_id", None)
    user_id = getattr(source, "user_id", None)
    user_name = getattr(source, "user_name", None)

    text = getattr(event, "text", "") or ""
    message_id = getattr(event, "message_id", None)
    reply_to_message_id = getattr(event, "reply_to_message_id", None)
    reply_to_text = getattr(event, "reply_to_text", None)

    # Determine sender_is_bot from the raw PTB message.
    raw = getattr(event, "raw_message", None)
    sender_is_bot = False
    if raw is not None:
        from_user = getattr(raw, "from_user", None)
        if from_user is not None:
            sender_is_bot = bool(getattr(from_user, "is_bot", False))

    mentions = ma_policy.extract_mentions_from_event(event)

    is_cmd = bool(text.startswith("/"))
    cmd_name = None
    if is_cmd:
        # get_command() strips the leading / and any @botname suffix
        first = text.lstrip("/").split(" ")[0].split("@")[0]
        cmd_name = first.lower() if first else None

    media_urls = getattr(event, "media_urls", []) or []
    media_types = getattr(event, "media_types", []) or []
    has_images = any(("image" in str(t).lower()) for t in media_types) or bool(media_urls)
    has_files = any(("file" in str(t).lower() or "document" in str(t).lower()) for t in media_types)
    has_audio = any(("audio" in str(t).lower() or "voice" in str(t).lower()) for t in media_types)

    return ma_policy.RouteInput(
        text=text,
        chat_id=str(chat_id),
        chat_type=chat_type,
        thread_id=str(thread_id) if thread_id is not None else None,
        user_id=str(user_id) if user_id is not None else None,
        user_name=user_name,
        message_id=str(message_id) if message_id is not None else None,
        reply_to_message_id=str(reply_to_message_id) if reply_to_message_id is not None else None,
        reply_to_text=reply_to_text,
        sender_is_bot=sender_is_bot,
        mentions=mentions,
        is_command=is_cmd,
        command_name=cmd_name,
        has_images=has_images,
        has_files=has_files,
        has_audio=has_audio,
    )


# ---------------------------------------------------------------------------
# Stage 2: orchestration intent recognition
# ---------------------------------------------------------------------------

def _recognise_orchestration_intent(text: str, cfg: ma_config.MultiAgentConfig
                                    ) -> Optional[Tuple[str, List[str]]]:
    """Decide whether @Hermes is being asked to orchestrate, and if so return
    ``(mode, target_agents)``.  Returns None for plain direct chat with Hermes.

    Per spec §7: explicit instructions win; clear multi-agent semantics may be
    inferred; abstract intent lets Hermes self-decide.  We avoid brittle
    keyword piles - this is a structured best-effort recogniser, and Hermes'
    own model (via the orchestrator's _summarise) carries the real judgment.

    Stage 2.5 (Manual-first / Natural continuity): the recogniser is deliberately
    BROAD so natural follow-ups ("问一下Claude还记得吗", "再查一下Codex",
    "让Claude看一下") are treated as delegation instead of falling through to
    Hermes' own model replying + searching on its own.  The real cost of a
    false positive (a delegation when the user just wanted to chat with Hermes)
    is low: Hermes still summarises; the user can say "不是，我是问你" to
    correct.  The cost of a false negative (Hermes answers instead of relaying)
    is the "second-relay no-reply" experience the user hit.

    Modes:
      DELEGATE   - "让/叫/请/问/查/看 Claude/Codex ..." (single-agent delegation)
      DISCUSSION - "你们讨论/充分讨论/一起看看" (multi-turn visible talk)
      EXECUTION  - "实现/修改...然后 Review" (implement + review rework loop)
      RESEARCH   - "分别分析/独立分析" (parallel independent analysis)
    """
    low = (text or "").lower()
    has_claude = "claude" in low or any(a in low for a in ("claude", "克劳德"))
    has_codex = "codex" in low or any(a in low for a in ("codex", "科达克斯"))
    both = has_claude and has_codex

    # Verbs that imply "relay/delegate to an agent".  Broadened in Stage 2.5 to
    # cover natural follow-up phrasings the original recogniser missed
    # ("问一下Claude还记得测试号码吗" -> must delegate, not Hermes self-search).
    delegate_verbs = ("让", "叫", "请", "去", "来", "问", "查", "查看", "看",
                      "确认", "回答", "告诉", "问问", "查查", "看看",
                      "分析", "检查", "评估", "review", "ask", "query")
    # Continuation markers: when present with an agent name, strongly imply a
    # follow-up delegation (natural continuity).
    followup_markers = ("还记不记得", "还记得", "刚才", "继续", "接着", "再问",
                        "再去", "再查", "再看", "再让", "上一轮", "上一个",
                        "之前", "刚才那个", "上个问题")

    def _agents_from_flags() -> List[str]:
        a = []
        if has_claude:
            a.append("claude")
        if has_codex:
            a.append("codex")
        return a or ["claude"]

    # Execution: implement + review (constraint: two-round rework).  Checked
    # before single-delegation so "让Claude实现..." is EXECUTION not DELEGATE.
    if any(k in low for k in ("实现", "修改", "改代码", "编码", "写代码", "重构")):
        if has_claude or has_codex or both:
            return "EXECUTION", _agents_from_flags()

    # Explicit single delegation.  Broadened: any delegate verb OR a follow-up
    # marker + exactly one named agent -> DELEGATE that agent.
    if (has_claude or has_codex) and not both:
        if any(v in low for v in delegate_verbs) or any(m in low for m in followup_markers):
            return "DELEGATE", _agents_from_flags()

    # Discussion: multi-turn visible talk.
    if any(k in low for k in ("讨论", "商量", "辩论", "一起看", "充分讨论", "你们三个")):
        agents = _agents_from_flags()
        if not (has_claude or has_codex):
            agents = ["claude", "codex"]  # "你们讨论" -> both
        return "DISCUSSION", agents

    # Parallel independent analysis.
    if any(k in low for k in ("分别分析", "独立分析", "各自分析", "同时分析")) and both:
        return "RESEARCH", ["claude", "codex"]

    # "让 Claude 和 Codex ..." without a clearer mode -> DELEGATE both.
    if both and any(k in low for k in ("让", "叫", "请", "问")):
        return "DELEGATE", ["claude", "codex"]

    return None


def _recognise_intervention(text: str) -> Optional[str]:
    """Detect a scheduling-level intervention on an active task (spec §8).

    Returns one of: 'pause', 'cancel', 'resume', or None.  These are global
    scheduling words aimed at @Hermes, not task content.
    """
    low = (text or "").lower()
    if any(k in low for k in ("暂停", "停一下", "pause", "先别")):
        return "pause"
    if any(k in low for k in ("取消", "终止", "不要了", "cancel", "stop task")):
        return "cancel"
    if any(k in low for k in ("继续", "恢复", "resume", "go on")):
        return "resume"
    return None


def _make_send_to_chat(gateway: Any, event: Any, chat_id: str):
    """Build a thread-safe send_to_chat callback for the orchestrator.

    The orchestrator runs in a background daemon thread (correction #3), so it
    CANNOT use the gateway's asyncio adapter directly from that thread - the
    adapter's httpx client is bound to the gateway's main event loop.  We
    capture the main loop here (while still on the gateway thread inside
    _on_pre_dispatch) and submit sends via run_coroutine_threadsafe.
    """
    import asyncio as _aio
    # Capture the running main loop NOW (we're on the gateway thread).
    main_loop = None
    try:
        main_loop = _aio.get_running_loop()
    except RuntimeError:
        main_loop = _aio.get_event_loop()
    # Resolve the adapter + chat_id once.
    source = getattr(event, "source", None)
    cid = str(getattr(source, "chat_id", "") or "") or str(chat_id)
    adapter = None
    adapters = getattr(gateway, "adapters", {}) or {}
    for a in adapters.values():
        adapter = a
        break

    def _send(text: str) -> None:
        if adapter is None or not cid or main_loop is None:
            logger.info("orchestrator (no-send) %s", text[:120])
            return
        async def _go():
            try:
                await adapter.send(cid, text)
            except Exception:
                logger.exception("multiagent: orchestrator adapter.send failed")
        try:
            if main_loop.is_running():
                _aio.run_coroutine_threadsafe(_go(), main_loop)
            else:
                # Loop not running (e.g. tests) - run synchronously.
                main_loop.run_until_complete(_go())
        except Exception:
            logger.exception("multiagent: orchestrator send_to_chat failed")
    return _send


def _make_llm_complete():
    """Build a llm_complete callback (system, user) -> text using the host-owned
    LLM facade captured in register().  Returns None if no facade is available,
    in which case the orchestrator falls back to a labelled digest."""
    facade = _llm_facade
    if facade is None:
        return None

    def _complete(system_prompt: str, user_prompt: str) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        result = facade.complete(messages, purpose="multiagent-orchestrator-summary")
        return getattr(result, "text", "") or ""

    return _complete


def _build_recent_context(store: Any, chat_id: str) -> str:
    """Lightweight recent-talk string for the planner (last few turns, no DAG)."""
    try:
        rows = store.get_recent_transcript(chat_id, limit=8)
    except Exception:
        logger.exception("multiagent: failed to read recent transcript for planner")
        return ""
    if not rows:
        return ""
    parts = []
    for r in rows:
        who = r.get("agent_id") or r.get("sender_type") or "?"
        txt = (r.get("text") or "").strip().replace("\n", " ")
        if txt:
            parts.append(f"[{who}] {txt[:200]}")
    return "\n".join(parts)


def _resolve_orchestration_plan(inp: Any, store: Any, cfg: ma_config.MultiAgentConfig
                                ) -> Optional[Any]:
    """Decide whether @Hermes should orchestrate, and return a SemanticPlan or
    None.  Three layers (需求 §3/§6, 追加修订):

      1. plan_from_keywords  - 100%-reliable deterministic fast-path (EXECUTION).
      2. plan_with_llm       - LLM understands the WHOLE message -> JSON plan.
         (No LLM available -> skip, fall through.)
      3. legacy _recognise_orchestration_intent - keyword recogniser, kept as a
         safety net for no-LLM/test environments.  Never the primary path now.

    ANSWER_SELF -> returns a plan (caller lets Hermes self-reply, no orchestrator).
    """
    from ._planner import plan_from_keywords, plan_with_llm, SemanticPlan
    # Layer 1: deterministic fast-path.
    fp = plan_from_keywords(inp.text)
    if fp is not None:
        logger.info("multiagent: plan via fast-path action=%s targets=%s", fp.action, fp.targets)
        return fp
    # Layer 2: LLM semantic planner (primary path).
    llm_complete = _make_llm_complete()
    if llm_complete is not None:
        recent = _build_recent_context(store, inp.chat_id)
        plan = plan_with_llm(inp.text, recent, llm_complete)
        if plan is not None:
            logger.info(
                "multiagent: plan via LLM action=%s targets=%s cont=%s detail=%s",
                plan.action, plan.targets, plan.continuation, plan.detail_requested,
            )
            return plan
        logger.info("multiagent: LLM planner returned None; falling back to keywords")
    # Layer 3: legacy keyword recogniser (safety net).
    intent = _recognise_orchestration_intent(inp.text, cfg)
    if intent is not None:
        mode, targets = intent
        from ._planner import SemanticPlan, _detect_detail_requested
        # Map legacy mode back to an action so the caller handles it uniformly.
        action = {"DELEGATE": "DELEGATE", "RESEARCH": "PARALLEL",
                  "DISCUSSION": "DISCUSS", "EXECUTION": "EXECUTE"}.get(mode, "DELEGATE")
        return SemanticPlan(
            action=action, targets=targets,
            detail_requested=_detect_detail_requested(inp.text), raw=inp.text,
        )
    return None


def _start_orchestration(inp: Any, mode: str, targets: List[str],
                         trace_id: str, store: Any, gateway: Any, event: Any,
                         plan: Any = None, detail_requested: bool = False) -> None:
    """Create the task and launch the background orchestrator (correction #3:
    non-blocking).  The orchestrator posts visibility messages itself."""
    from .orchestrator import Orchestrator, TaskRequest
    send_cb = _make_send_to_chat(gateway, event, inp.chat_id)
    req = TaskRequest(
        chat_id=inp.chat_id,
        user_id=inp.user_id or "unknown",
        user_request=inp.text,
        mode=mode,
        target_agents=targets,
        reply_to_msg_id=inp.reply_to_message_id or "",
        send_to_chat=send_cb,
        llm_complete=_make_llm_complete(),
        plan=plan,
        detail_requested=detail_requested,
    )
    orch = Orchestrator(store, req)

    # Wrap start so we register/unregister the orchestrator and tag the
    # task's transcript rows with the real task_id (for Reply routing).
    original_start = orch.start

    def _start_and_register() -> str:
        task_id = original_start()
        _register_orch(task_id, orch)
        # Re-tag the transcript row for the user's triggering message so a
        # later Reply to it resolves to this task (constraint #5 routing).
        try:
            store.record_transcript({
                "msg_id": inp.message_id or "",
                "platform": "telegram",
                "chat_id": inp.chat_id,
                "thread_id": inp.thread_id,
                "sender_type": "human",
                "sender_id": inp.user_id or "",
                "sender_name": inp.user_name or "",
                "agent_id": "hermes",
                "text": (inp.text or "")[:2000],
                "reply_to_msg_id": inp.reply_to_message_id or "",
                "task_id": task_id,
                "trace_id": trace_id,
                "trigger_type": "orchestrator",
                "route_reason": f"orchestration:{mode}",
                "observed": 0,
            })
        except Exception:
            logger.exception("multiagent: failed to tag trigger transcript")
        # Spawn a reaper to unregister when the task finishes.
        import threading as _th
        def _reaper():
            if orch._thread is not None:
                orch._thread.join()
            _unregister_orch(task_id)
        _th.Thread(target=_reaper, name=f"ma-reaper-{task_id}", daemon=True).start()
        return task_id

    orch.start = _start_and_register  # type: ignore[assignment]
    orch.start()


def _handle_intervention(intervention: str, inp: Any, store: Any,
                         gateway: Any, event: Any) -> bool:
    """Apply a pause/cancel/resume to active task(s) in this chat (constraint
    #5).  Returns True if handled (caller should skip).  If multiple active
    tasks exist and the intent can't be uniquely resolved, ask for
    clarification instead of mis-scheduling."""
    active = _active_orchs_for_chat(inp.chat_id)
    if not active:
        return False  # nothing to intervene on; fall through to normal handling

    if len(active) > 1:
        # Ambiguous: list the active tasks and ask the user to clarify.
        lines = ["⚠️ 当前有多个活跃任务，请明确要操作哪一个："]
        for orch in active:
            t = store.get_task(orch.task_id)
            preview = (t or {}).get("mode", "?")
            lines.append(f"  • 任务 {orch.task_id}（{preview}）")
        lines.append("回复对应任务的消息，或注明任务 ID。")
        try:
            _send_notice(gateway, event, "\n".join(lines))
        except Exception:
            logger.exception("multiagent: failed to send clarification")
        return True

    orch = active[0]
    if intervention == "pause":
        orch.pause()
    elif intervention == "cancel":
        orch.cancel()
    elif intervention == "resume":
        orch.resume()
    return True


def _on_pre_dispatch(event: Any, gateway: Any = None, session_store: Any = None, **kw: Any) -> Optional[Dict[str, Any]]:
    """The hard gate.  Returns {action: skip|allow} per the pre_gateway_dispatch
    contract (gateway/run.py:9968).  We also mutate event.metadata in place to
    attach routing context downstream."""
    cfg = _get_cfg()
    if not cfg.enabled:
        return None  # plugin disabled -> normal dispatch

    # Only govern the configured group chat.  DMs and other chats pass through
    # (DMs are always-for-this-bot; the policy.decide handles chat_type=='dm').
    source = getattr(event, "source", None)
    chat_id = str(getattr(source, "chat_id", "") or "")
    if cfg.group_chat_id and chat_id != cfg.group_chat_id:
        # Not our governed group - but still record if it's a group? No:
        # only govern the designated group to avoid surprising other chats.
        return None

    _ensure_receiver_started()

    # Stash the event so /ma* command handlers (which only receive raw_args)
    # can read reply_to_message_id etc.
    from . import commands as ma_commands
    ma_commands.stash_event(event)

    store = get_store()
    inp = _build_route_input(event)

    # --- Idempotency: dedup by (chat_id, msg_id) ---
    idem_key = f"{inp.chat_id}:{inp.message_id}" if inp.message_id else f"{inp.chat_id}:{hash(inp.text)}"
    is_first = store.check_and_mark_idempotent(idem_key, action="pre_dispatch")
    if not is_first:
        logger.info("multiagent: idempotent skip (dup) chat=%s msg=%s", inp.chat_id, inp.message_id)
        return {"action": "skip", "reason": "duplicate message (idempotency)"}

    # --- Determine the replied-to agent for cross-agent reference ---
    reply_target_agent: Optional[str] = None
    if inp.reply_to_message_id:
        reply_target_agent = store.get_agent_for_msgid(inp.chat_id, inp.reply_to_message_id)

    # --- Route decision ---
    decision = ma_policy.decide(inp, cfg, reply_target_agent=reply_target_agent)
    trace_id = uuid.uuid4().hex[:16]

    # --- Record to Transcript ---
    agent_id = "human"  # default for inbound human messages
    if inp.sender_is_bot:
        # A bot-origin message arriving at Hermes (e.g. another bot @'d Hermes).
        # Determine which agent from the reply/mention if possible.
        agent_id = reply_target_agent or "bot"
    store.record_transcript({
        "msg_id": inp.message_id or "",
        "platform": "telegram",
        "chat_id": inp.chat_id,
        "thread_id": inp.thread_id,
        "sender_type": "bot" if inp.sender_is_bot else "human",
        "sender_id": inp.user_id or "",
        "sender_name": inp.user_name or "",
        "agent_id": agent_id,
        "text": inp.text[:2000] if inp.text else "",
        "reply_to_msg_id": inp.reply_to_message_id or "",
        "task_id": trace_id,
        "trace_id": trace_id,
        "trigger_type": decision.trigger_type,
        "route_reason": decision.route_reason,
        "observed": 1 if decision.observed else 0,
        "has_images": 1 if inp.has_images else 0,
        "has_files": 1 if inp.has_files else 0,
        "has_audio": 1 if inp.has_audio else 0,
    })

    # --- Record route log + task envelope ---
    store.record_route(
        trace_id=trace_id,
        msg_id=inp.message_id or "",
        target_agent=",".join(decision.target_agents) if decision.target_agents else "none",
        trigger_type=decision.trigger_type,
        route_reason=decision.route_reason,
        wrote_session=decision.should_write_session,
        wrote_shared=decision.should_write_shared,
    )
    store.record_task_envelope({
        "task_id": trace_id,
        "trace_id": trace_id,
        "source": inp.user_id or "unknown",
        "target_agents": decision.target_agents,
        "trigger_type": decision.trigger_type,
        "reply_to_msg_id": inp.reply_to_message_id or "",
        "reference_msg_ids": [inp.reply_to_message_id] if inp.reply_to_message_id else [],
        "memory_policy": decision.memory_policy,
        "status": "dispatched" if decision.should_dispatch else "skipped",
        "idempotency_key": idem_key,
        "hop_count": 0,
        "max_hops": 0,  # no relay this stage
    })

    # --- Apply the decision ---
    if not decision.should_dispatch:
        reason = decision.route_reason
        if decision.notice:
            # @all or similar: send the notice to the chat, then skip the turn.
            try:
                _send_notice(gateway, event, decision.notice)
            except Exception:
                logger.exception("multiagent: failed to send notice")
            reason = decision.notice
        logger.info("multiagent: skip chat=%s msg=%s reason=%s", inp.chat_id, inp.message_id, reason)
        return {"action": "skip", "reason": reason}

    # Dispatch allowed - inject reference context + shared memory for Hermes.
    if decision.reference_context:
        event.metadata["reference_context"] = decision.reference_context
    event.metadata["route_target_agents"] = decision.target_agents
    event.metadata["route_trigger_type"] = decision.trigger_type
    event.metadata["route_trace_id"] = trace_id

    # Inject active Shared Memory (read-only) into the Hermes context.
    if decision.should_write_session:
        scope_id = inp.thread_id if inp.thread_id else inp.chat_id
        scope_type = "topic" if inp.thread_id else cfg.default_scope_type
        shared_text = store.get_active_shared_memory_text(scope_type, scope_id)
        if shared_text:
            existing = getattr(event, "channel_context", None) or ""
            event.channel_context = (existing + "\n\n" + shared_text).strip() if existing else shared_text

    # --- Stage 2: orchestration & intervention ---
    # Reply-to-task routing (constraint #5): if the user replied to a message
    # that belongs to an active task, this is a local correction for that task
    # - route it there, not into a fresh direct-chat session.  A bare @Agent
    # without a task-message reply still goes to direct chat (spec §8.3).
    if inp.reply_to_message_id and not inp.sender_is_bot:
        replied_task = store.get_task_for_msg(inp.chat_id, inp.reply_to_message_id)
        if replied_task:
            active = _active_orchs_for_chat(inp.chat_id)
            target_orch = next((o for o in active if o.task_id == replied_task), None)
            if target_orch is not None:
                # Record the user intervention on the task and surface it.
                try:
                    store.update_task(replied_task, user_intervention=1)
                except Exception:
                    logger.exception("multiagent: failed to mark user_intervention")
                logger.info(
                    "multiagent: reply-to-task %s routed (local correction)",
                    replied_task,
                )
                # The orchestrator's next turn picks up the correction via the
                # task's discussion context (the user's text is in the reply).
                # Skip Hermes' direct reply so we don't open a parallel session.
                try:
                    _send_notice(gateway, event,
                                 f"↩️ 已收到对任务 {replied_task} 的纠偏，将在下一轮纳入。")
                except Exception:
                    logger.exception("multiagent: failed to send reply-task notice")
                return {"action": "skip", "reason": f"reply-to-task:{replied_task}"}

    is_hermes_mention = (
        decision.trigger_type == "mention" and decision.target_agents == ["hermes"]
    )
    if is_hermes_mention and not inp.sender_is_bot:
        # 1. Intervention check: pause/cancel/resume on an active task.
        intervention = _recognise_intervention(inp.text)
        if intervention is not None:
            handled = _handle_intervention(intervention, inp, store, gateway, event)
            if handled:
                return {"action": "skip", "reason": f"intervention:{intervention}"}
        # 2. Semantic plan: fast-path -> LLM planner -> legacy keywords (追加修订).
        #    The LLM understands the WHOLE message; keywords are only a safety
        #    net, not the primary path (需求 §3/§6).
        plan = _resolve_orchestration_plan(inp, store, cfg)
        if plan is not None:
            from ._planner import plan_to_mode_targets
            # ANSWER_SELF: user wants Hermes itself to reply -> allow (no orchestrator).
            if plan.action == "ANSWER_SELF":
                logger.info("multiagent: plan=ANSWER_SELF, letting Hermes self-reply")
                # Fall through to "allow" so Hermes' own model answers.
            elif plan.action == "CLARIFY":
                try:
                    _send_notice(gateway, event,
                                 "🤔 我没完全确定你的意图。你是想让我自己回答，"
                                 "还是让 Claude / Codex 来做？可以再说清楚一点。")
                except Exception:
                    logger.exception("multiagent: failed to send clarify notice")
                return {"action": "skip", "reason": "planner:CLARIFY"}
            else:
                mt = plan_to_mode_targets(plan)
                if mt is not None:
                    mode, targets = mt
                    _start_orchestration(
                        inp, mode, targets, trace_id, store, gateway, event,
                        plan=plan, detail_requested=plan.detail_requested,
                    )
                    return {"action": "skip", "reason": f"orchestrator:{mode}"}

    logger.info(
        "multiagent: allow chat=%s msg=%s targets=%s trigger=%s",
        inp.chat_id, inp.message_id, decision.target_agents, decision.trigger_type,
    )
    return {"action": "allow"}


def _send_notice(gateway: Any, event: Any, text: str) -> None:
    """Best-effort send a short notice to the chat (e.g. @all not enabled)."""
    if gateway is None:
        return
    source = getattr(event, "source", None)
    chat_id = str(getattr(source, "chat_id", "") or "")
    if not chat_id:
        return
    # Use the gateway's adapter to send.  We look for the telegram adapter.
    adapters = getattr(gateway, "adapters", {}) or {}
    adapter = None
    for a in adapters.values():
        adapter = a
        break
    if adapter is None:
        return
    import asyncio
    async def _go():
        try:
            await adapter.send(chat_id, text)
        except Exception:
            pass
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_go(), loop=loop)
        else:
            loop.run_until_complete(_go())
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Called by the plugin loader at gateway startup."""
    global _llm_facade
    cfg = _get_cfg()
    if not cfg.enabled:
        logger.warning("multiagent: register() called but plugin is disabled")
        return

    # Capture the host-owned LLM facade so the orchestrator can call Hermes'
    # own model for genuine understanding/summarisation (not copy-paste).
    try:
        _llm_facade = ctx.llm
        logger.info("multiagent: LLM facade captured (orchestrator summarisation enabled)")
    except Exception:
        logger.exception("multiagent: failed to capture LLM facade; summarisation will fall back")

    ctx.register_hook("pre_gateway_dispatch", _on_pre_dispatch)

    # Register namespaced slash commands (avoid colliding with cc-connect's
    # built-in /new /status /stop /help ... which broadcast to all 3 bots).
    from . import commands as ma_commands

    ctx.register_command("mashare", ma_commands.handle_share,
                         description="Write a shared-memory fact. Usage: /mashare <text>  (or reply to a message + /mashare)")
    ctx.register_command("maforget", ma_commands.handle_forget,
                         description="Logically delete a shared-memory fact. Usage: /maforget <memory_id>")
    ctx.register_command("mashared", ma_commands.handle_shared,
                         description="List active shared-memory facts for the current scope.")
    ctx.register_command("maroute", ma_commands.handle_route,
                         description="Show why a message was routed. Usage: /maroute [msg_id]")
    ctx.register_command("macontext", ma_commands.handle_context,
                         description="Show an agent's session summary. Usage: /macontext @Agent")
    ctx.register_command("macancel", ma_commands.handle_cancel,
                         description="Cancel Hermes' running task for this group. Usage: /macancel @Agent")
    ctx.register_command("manew", ma_commands.handle_new,
                         description="Reset Hermes' group session. Usage: /manew @Agent")

    # Stage 2: start the localhost hook receiver NOW (at gateway startup), not
    # lazily on the first group message.  cc-connect fires message.received /
    # message.sent_delivered hooks as fire-and-forget POSTs; if the receiver
    # isn't listening yet (e.g. cc-connect processed a message before the first
    # group message reached Hermes), those POSTs are dropped silently.  Starting
    # here guarantees the receiver is ready before cc-connect can fire anything.
    # See constraint #3: the hook/msgid data chain must work reliably in real TG.
    _ensure_receiver_started()

    logger.info(
        "multiagent: registered pre_gateway_dispatch hook + 7 /ma* commands. "
        "group=%s agents=%s receiver=%s",
        cfg.group_chat_id, list(cfg.agents.keys()),
        "up" if _receiver_started else "DOWN (check secret/config)",
    )

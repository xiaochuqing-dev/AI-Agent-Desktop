"""Slash command handlers for the multi-agent governance plugin.

All commands use the ``ma`` namespace prefix to avoid colliding with cc-connect's
built-in commands (/new /status /stop /help /cancel ...) which, under Telegram's
bare-command broadcast, would otherwise trigger all 3 bots simultaneously.

Handler signature: ``fn(raw_args: str) -> str | None`` (sync or async), per
``hermes_cli.plugins.PluginContext.register_command``.

Session context (chat_id / thread_id / user_id) is read via the gateway's
session ContextVars (``get_session_env``).  The triggering event (for
reply_to_message_id) is stashed by the ``pre_gateway_dispatch`` hook in
``_last_event`` before command dispatch.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from . import config as ma_config
from .store import get_store

logger = logging.getLogger(__name__)

# Stashed by _on_pre_dispatch right before command dispatch, so /mashare can
# read reply_to_message_id.  Single-slot is fine: commands are processed
# serially per session.
_last_event: Optional[Any] = None
_last_event_lock = __import__("threading").Lock()


def stash_event(event: Any) -> None:
    """Called by pre_gateway_dispatch to make the current event available to
    command handlers."""
    global _last_event
    with _last_event_lock:
        _last_event = event


def _pop_event() -> Optional[Any]:
    global _last_event
    with _last_event_lock:
        return _last_event


def _ctx() -> Dict[str, str]:
    """Read session context from the gateway ContextVars."""
    try:
        from gateway.session_context import get_session_env
        return {
            "chat_id": get_session_env("HERMES_SESSION_CHAT_ID"),
            "thread_id": get_session_env("HERMES_SESSION_THREAD_ID"),
            "user_id": get_session_env("HERMES_SESSION_USER_ID"),
            "platform": get_session_env("HERMES_SESSION_PLATFORM"),
        }
    except Exception:
        return {"chat_id": "", "thread_id": "", "user_id": "", "platform": ""}


def _cfg() -> ma_config.MultiAgentConfig:
    from . import _get_cfg
    return _get_cfg()


def _scope(ctx: Dict[str, str], cfg: ma_config.MultiAgentConfig):
    """Resolve (scope_type, scope_id) for the current chat/thread."""
    if ctx["thread_id"]:
        return "topic", ctx["thread_id"]
    if cfg.default_scope_type == "project":
        return "project", cfg.group_chat_id or ctx["chat_id"]
    return cfg.default_scope_type or "group", ctx["chat_id"]


# ---------------------------------------------------------------------------
# /mashare <text>   |   reply to a message + /mashare
# ---------------------------------------------------------------------------

def handle_share(raw_args: str) -> str:
    cfg = _cfg()
    ctx = _ctx()
    if not cfg.is_admin(ctx["user_id"]):
        return "⛔ 只有管理员可以写入共享记忆。"
    if not ctx["chat_id"]:
        return "⚠️ 无法确定当前会话作用域。"

    store = get_store()
    scope_type, scope_id = _scope(ctx, cfg)

    event = _pop_event()
    reply_to_msg_id = None
    if event is not None:
        rmid = getattr(event, "reply_to_message_id", None)
        if rmid:
            reply_to_msg_id = str(rmid)

    text = (raw_args or "").strip()
    # Handle "/mashare @all text" -> strip @all, still single-scope write
    # (we do NOT broadcast in this stage; @all broadcast is next stage).
    at_all = False
    for alias in cfg.at_all_aliases:
        if alias.lower() in text.lower():
            at_all = True
            text = text.replace(alias, "").strip()
            break

    if reply_to_msg_id and not text:
        # reply to a message + bare /mashare -> store the replied message's text
        reply_text = getattr(event, "reply_to_text", None) if event else None
        if reply_text:
            text = reply_text
        else:
            # Try the shared transcript
            entry = store.get_transcript_entry(ctx["chat_id"], reply_to_msg_id)
            if entry:
                text = entry.get("text") or ""
        if not text:
            return "⚠️ 回复的消息没有可保存的文本内容。"
        content = text[:2000]
    elif text:
        content = text[:2000]
    else:
        return ("用法:\n"
                "  /mashare <共享事实文字>\n"
                "  回复某条消息 + /mashare  (保存被回复内容)\n"
                "  /mashare @all <文字>  (写入共享记忆；@all 广播下一阶段启用)")

    mid = store.add_shared_memory(
        scope_type=scope_type, scope_id=scope_id,
        content=content, created_by=ctx["user_id"] or "unknown",
        source_msg_id=reply_to_msg_id,
    )
    extra = ""
    if at_all:
        extra = "\n(注：@all 广播当前未启用，共享记忆已写入当前作用域，三个 Agent 可通过 /mashared 查看。Claude/Codex 实时读取需下一阶段 Relay。)"
    return f"✅ 共享记忆已写入 (id={mid}, scope={scope_type}/{scope_id}){extra}"


# ---------------------------------------------------------------------------
# /maforget <memory_id>
# ---------------------------------------------------------------------------

def handle_forget(raw_args: str) -> str:
    cfg = _cfg()
    ctx = _ctx()
    if not cfg.is_admin(ctx["user_id"]):
        return "⛔ 只有管理员可以删除共享记忆。"
    mid = (raw_args or "").strip().split()[0] if raw_args.strip() else ""
    if not mid:
        return "用法: /maforget <memory_id>"
    store = get_store()
    if store.forget_shared_memory(mid):
        return f"✅ 共享记忆 {mid} 已逻辑删除（保留审计记录）。"
    return f"⚠️ 未找到有效的共享记忆 {mid}。"


# ---------------------------------------------------------------------------
# /mashared
# ---------------------------------------------------------------------------

def handle_shared(raw_args: str) -> str:
    cfg = _cfg()
    ctx = _ctx()
    if not ctx["chat_id"]:
        return "⚠️ 无法确定当前会话作用域。"
    store = get_store()
    scope_type, scope_id = _scope(ctx, cfg)
    rows = store.list_shared_memory(scope_type=scope_type, scope_id=scope_id)
    if not rows:
        return f"当前作用域 ({scope_type}/{scope_id}) 没有活跃的共享记忆。"
    lines = [f"📋 共享记忆 ({scope_type}/{scope_id}) — {len(rows)} 条:"]
    for r in rows:
        src = f" src={r['source_msg_id']}" if r["source_msg_id"] else ""
        lines.append(f"  [{r['memory_id']}] {r['content'][:120]}{src}  ({r['status']})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /maroute [msg_id]
# ---------------------------------------------------------------------------

def handle_route(raw_args: str) -> str:
    ctx = _ctx()
    store = get_store()
    msg_id = (raw_args or "").strip().split()[0] if raw_args.strip() else None

    if not msg_id:
        # Show last 10 route logs for this chat
        logs = store.get_route_log(limit=10)
    else:
        logs = store.get_route_log(msg_id=msg_id)

    if not logs:
        return "没有路由记录。" if not msg_id else f"消息 {msg_id} 没有路由记录。"

    lines = ["🔍 路由记录:"]
    for r in logs[:10]:
        lines.append(
            f"  msg={r['msg_id']} → {r['target_agent']}  "
            f"trigger={r['trigger_type']}  reason={r['route_reason']}  "
            f"session={'✓' if r['wrote_session'] else '✗'}  "
            f"shared={'✓' if r['wrote_shared'] else '✗'}  "
            f"trace={r['trace_id'][:8]}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /macontext @Agent
# ---------------------------------------------------------------------------

def handle_context(raw_args: str) -> str:
    cfg = _cfg()
    ctx = _ctx()
    agent = (raw_args or "").strip().lstrip("@").lower()
    if not agent:
        return "用法: /macontext @Agent  (Agent: hermes | claude | codex)"

    if agent == "hermes":
        # Hermes session summary - we can query our own state.db
        try:
            import sqlite3
            from hermes_constants import get_hermes_home
            db = get_hermes_home() / "state.db"
            if db.exists():
                conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    "SELECT id, display_name, message_count, model, started_at "
                    "FROM sessions WHERE session_key LIKE ? ORDER BY started_at DESC LIMIT 1",
                    (f"%{ctx['chat_id']}%",),
                )
                row = cur.fetchone()
                conn.close()
                if row:
                    return (f"🤖 Hermes 当前群聊会话:\n"
                            f"  session_id: {row['id']}\n"
                            f"  标题: {row['display_name'] or '(无)'}\n"
                            f"  消息数: {row['message_count']}\n"
                            f"  模型: {row['model'] or '(默认)'}\n"
                            f"  开始: {row['started_at']}")
                return "Hermes 在当前群聊没有会话记录。"
        except Exception as e:
            return f"⚠️ 查询 Hermes 会话失败: {e}"
    else:
        # Claude/Codex - we cannot directly read cc-connect sessions without
        # the management API.  Provide guidance.
        return (f"🤖 {agent}: 当前阶段无法直接查询 cc-connect 会话摘要。\n"
                f"  可用 `cc-connect sessions list` / `cc-connect sessions show <id>` 间接查看。\n"
                f"  🟡 实时会话上下文查询待下一阶段 Relay/Gateway 补齐。")


# ---------------------------------------------------------------------------
# /macancel @Agent
# ---------------------------------------------------------------------------

def handle_cancel(raw_args: str) -> str:
    cfg = _cfg()
    ctx = _ctx()
    agent = (raw_args or "").strip().lstrip("@").lower()
    if not agent:
        return "用法: /macancel @Agent  (Agent: hermes | claude | codex)"

    if agent == "hermes":
        # Cancel Hermes' running task for this session.
        # We access the gateway runner via the plugin context if available.
        # The cleanest path: evict the cached agent for this session_key.
        try:
            from gateway.session_context import get_session_env
            session_key_env = os.getenv("HERMES_SESSION_KEY", "")
            if not session_key_env:
                return "⚠️ 无法确定当前 session key。"
            # We can't directly call _release_running_agent_state from here
            # without a gateway reference.  Return guidance for now; the
            # built-in /stop already cancels Hermes tasks.
            return ("ℹ️ 取消 Hermes 任务请使用内置 /stop 命令（直接发给 Hermes）。\n"
                    "  /macancel @hermes 当前作为提示；未来可通过插件上下文直接取消。")
        except Exception as e:
            return f"⚠️ 取消失败: {e}"
    else:
        return (f"🤖 {agent}: cc-connect 侧任务取消请直接对该 Bot 发送 /stop。\n"
                f"  🟡 跨 Bot 取消待下一阶段 Relay/Gateway 补齐。")


# ---------------------------------------------------------------------------
# /manew @Agent
# ---------------------------------------------------------------------------

def handle_new(raw_args: str) -> str:
    cfg = _cfg()
    ctx = _ctx()
    agent = (raw_args or "").strip().lstrip("@").lower()
    if not agent:
        return "用法: /manew @Agent  (Agent: hermes | claude | codex)"

    if agent == "hermes":
        # Reset Hermes' group session.  The built-in /new already does this
        # for the current session.  We guide the user.
        return ("ℹ️ 重置 Hermes 群聊会话请使用内置 /new 命令（直接发给 Hermes 或 /new@Hermes_bot）。\n"
                "  /manew @hermes 当前作为提示；只影响 Hermes，不影响 Claude/Codex/Shared Memory。")
    elif agent in ("claude", "codex"):
        # Stage 2.5: bump the relay conversation epoch for this (chat, agent).
        # The NEXT Hermes->agent delegation will open a fresh cc-connect relay
        # session (relay:hermes-conv_{chat}_{agent}_{epoch+1}:...), so the agent
        # starts a clean conversation.  Existing direct @Claude / @Codex chats
        # keep their own cc-connect sessions (use the bot's own /new for those).
        try:
            store = get_store()
            # chat_id comes from the stashed event source.
            ev = _pop_event()
            chat_id = ""
            if ev is not None:
                src = getattr(ev, "source", None)
                chat_id = str(getattr(src, "chat_id", "") or "")
                # Re-stash so a later /ma* command in the same dispatch still sees it.
                stash_event(ev)
            if not chat_id:
                return ("⚠️ 无法确定当前群 chat_id；请在群内发送 /manew @" + agent + "。")
            new_epoch = store.bump_relay_conversation_epoch(chat_id, agent)
            return (f"🔄 已为 {agent} 切换到新会话轮次（epoch={new_epoch}）。\n"
                    f"  下次 Hermes 委派 {agent} 时将开启全新对话。\n"
                    f"  直接 @ {agent} 的会话不受影响（需对该 Bot 发 /new）。")
        except Exception as e:
            return f"⚠️ 切换 {agent} 会话失败: {e}"
    else:
        return (f"🤖 {agent}: 未知 Agent。可用: hermes | claude | codex")

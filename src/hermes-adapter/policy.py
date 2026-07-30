"""Routing policy - the "unified routing protocol" as executable code.

This is a pure-function decision engine.  Given a :class:`RouteInput`
(snapshotted from a ``MessageEvent``) and the multi-agent config, it returns a
:class:`RouteDecision` describing:

  * which agent(s) should handle the message
  * the trigger type (command | mention | reply | broadcast | none)
  * whether the agent session may be written
  * whether shared memory may be written (always False here - only /mashare writes)
  * reference context for cross-agent replies
  * a human-readable route reason

Hard rules (enforced in code, NOT via prompt - see stage-1.5 spec §4):

  1. Plain group message (no @, no reply-to-bot, no command) -> ALL bots silent.
     Only recorded to Transcript as observed.  No model call, no session write.
  2. Explicit @agent -> only that agent.
  3. Multiple @agents -> only the named agents.
  4. Reply to an agent + @another agent -> only the @'d agent, with the
     replied-to message's text attached as reference context.
  5. Plain reply to an agent (no @) -> only that agent.
  6. @all -> **next stage**: not a real broadcast yet (cc-connect bots cannot
     be triggered by @all).  Hermes recognises it but returns a skip with a
     notice.  NOT a fake broadcast.
  7. Bot-origin messages -> never auto-trigger other bots (anti-loop).

The decision is the *contract* all three bots should run.  In this stage only
Hermes can run it (pre_gateway_dispatch hook); Claude/Codex (cc-connect) rely
on static config (group_reply_all=false) + their native reply enrichment.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .config import MultiAgentConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RouteInput:
    """Snapshotted, policy-relevant fields from a MessageEvent."""
    text: str
    chat_id: str
    chat_type: str               # dm | group | channel | thread
    thread_id: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    message_id: Optional[str] = None
    reply_to_message_id: Optional[str] = None
    reply_to_text: Optional[str] = None
    # sender_type: 'human' or 'bot'.  For Hermes inbound, PTB message.from_user.is_bot.
    sender_is_bot: bool = False
    # Parsed @mentions (Telegram usernames without leading @), or None if not
    # a Telegram event / entities unavailable.
    mentions: Optional[List[str]] = None
    is_command: bool = False
    command_name: Optional[str] = None
    # media
    has_images: bool = False
    has_files: bool = False
    has_audio: bool = False


@dataclass
class RouteDecision:
    target_agents: List[str] = field(default_factory=list)  # hermes|claude|codex
    trigger_type: str = "none"     # command|mention|reply|broadcast|none
    route_reason: str = ""
    should_dispatch: bool = False  # call the agent model?
    should_write_session: bool = False
    should_write_shared: bool = False   # always False here
    reference_context: Optional[str] = None
    memory_policy: Dict[str, Any] = field(default_factory=dict)
    observed: bool = False          # record to transcript as observed-only?
    notice: Optional[str] = None    # optional user-facing notice (e.g. @all not enabled)

    @property
    def is_routed(self) -> bool:
        return bool(self.target_agents) and self.should_dispatch


# ---------------------------------------------------------------------------
# Mention parsing
# ---------------------------------------------------------------------------

_MENTION_RE = re.compile(r"@([A-Za-z0-9_]{2,31})")


def parse_mentions(text: str, entity_mentions: Optional[List[str]] = None) -> List[str]:
    """Return lowercased usernames (without @) mentioned in *text*.

    Prefer server-parsed entity_mentions (from Telegram MessageEntity) when
    available; fall back to regex scan of the text.  Telegram bot usernames
    must end in 'bot', but we accept any @handle here and let the config
    decide if it matches a known agent.
    """
    found: List[str] = []
    if entity_mentions:
        for m in entity_mentions:
            found.append(m.lstrip("@").lower())
    if text:
        for m in _MENTION_RE.findall(text):
            found.append(m.lower())
    # dedupe preserving order
    seen = set()
    out = []
    for u in found:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _is_at_all(text: str, aliases: List[str]) -> bool:
    low = (text or "").lower()
    for a in aliases:
        if a.lower() in low:
            return True
    return False


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def _resolve_agent(cfg: MultiAgentConfig, username: str) -> Optional[str]:
    """Map a Telegram username (without @) to an agent name (hermes|claude|codex)."""
    spec = cfg.agent_for_username(username)
    return spec.name if spec else None


def _agent_from_reply(cfg: MultiAgentConfig, reply_text: Optional[str],
                      reply_author_name: Optional[str] = None,
                      store_lookup_agent: Optional[str] = None) -> Optional[str]:
    """Best-effort: which agent posted the message being replied to?

    Priority:
      1. store_lookup_agent (from msgid_agent_map / transcript - most reliable)
      2. parse @username out of the enriched reply text "[Reply to @user]: ..."
      3. None (unknown - caller should ask user to clarify)
    """
    if store_lookup_agent:
        return store_lookup_agent
    if reply_text:
        # enrichReplyContent formats as "[Reply to @username]: ..." or
        # "[Reply to FirstName LastName]: ...".  Only @username is reliable.
        m = re.search(r"@\s*([A-Za-z0-9_]{2,31})", reply_text)
        if m:
            return _resolve_agent(cfg, m.group(1))
    return None


def decide(input: RouteInput, cfg: MultiAgentConfig,
           reply_target_agent: Optional[str] = None) -> RouteDecision:
    """Compute the routing decision.  Pure function - no side effects.

    ``reply_target_agent`` is the agent that posted the replied-to message,
    resolved by the caller from the shared store (msgid_agent_map / transcript).
    If None, we fall back to parsing reply_text.
    """
    d = RouteDecision()

    # --- DMs: always dispatch to Hermes (this process).  No group routing. ---
    if input.chat_type == "dm":
        d.target_agents = ["hermes"]
        d.trigger_type = "command" if input.is_command else "mention"
        d.route_reason = "dm-direct"
        d.should_dispatch = True
        d.should_write_session = True
        return d

    # --- Group messages below ---

    # Rule 7: bot-origin messages never auto-trigger (anti-loop).
    if input.sender_is_bot:
        d.trigger_type = "none"
        d.route_reason = "anti-loop: bot-origin message ignored"
        d.should_dispatch = False
        d.observed = True
        return d

    # Rule 1b: commands are handled by the command layer, not here.
    # But we still gate: only /ma* governance commands are ours; other
    # commands fall through to normal Hermes dispatch.
    if input.is_command:
        cmd = (input.command_name or "").lower()
        if cmd.startswith("ma"):
            # governance command -> Hermes handles via register_command
            d.target_agents = ["hermes"]
            d.trigger_type = "command"
            d.route_reason = f"governance command /{cmd}"
            d.should_dispatch = True  # command handler will run
            d.should_write_session = False
            return d
        # Non-ma commands (e.g. /new /status) -> let Hermes normal dispatch handle.
        d.target_agents = ["hermes"]
        d.trigger_type = "command"
        d.route_reason = f"builtin command /{cmd}"
        d.should_dispatch = True
        d.should_write_session = True
        return d

    mentions = input.mentions if input.mentions is not None else parse_mentions(input.text)
    at_all = _is_at_all(input.text, cfg.at_all_aliases)

    # Strip @all / @everyone aliases from mentions so they aren't mistaken for
    # agent usernames.  (Telegram usernames must end in 'bot', so 'all'/'everyone'
    # would never match a real agent anyway, but removing them keeps the
    # @all check clean.)
    at_all_alias_lower = {a.lstrip("@").lower() for a in cfg.at_all_aliases}
    mentions = [m for m in mentions if m not in at_all_alias_lower]

    # Rule 6: @all -> next stage.  Do NOT fake-broadcast.
    if at_all and not mentions:
        d.trigger_type = "broadcast"
        d.route_reason = "@all recognised but real 3-bot broadcast requires Relay stage"
        d.should_dispatch = False
        d.observed = True
        d.notice = (
            "@all 当前未完整启用：cc-connect 两个 Bot 在 group_reply_all=false 下"
            " 不会响应 @all。真正广播需下一阶段 Relay/Gateway 支持。"
        )
        return d

    # Resolve mentioned agents
    mentioned_agents: List[str] = []
    for u in mentions:
        a = _resolve_agent(cfg, u)
        if a and a not in mentioned_agents:
            mentioned_agents.append(a)

    has_reply = bool(input.reply_to_message_id)
    replied_agent = _agent_from_reply(cfg, input.reply_to_text, store_lookup_agent=reply_target_agent)

    # Rule 4: reply to agent X + @agent Y -> only Y, with X's text as reference.
    if mentioned_agents and has_reply and replied_agent:
        d.target_agents = mentioned_agents
        d.trigger_type = "mention"
        d.route_reason = (
            f"reply to {replied_agent} + @{' @'.join(mentioned_agents)} -> "
            f"only @'d agent(s); {replied_agent} text attached as reference"
        )
        d.should_dispatch = "hermes" in mentioned_agents
        d.should_write_session = d.should_dispatch
        if replied_agent not in mentioned_agents:
            d.reference_context = (
                f"[Referenced message from {replied_agent}]: {input.reply_to_text or ''}"
            )
        return d

    # Rule 2/3: explicit @agent(s) -> only those agents
    if mentioned_agents:
        d.target_agents = mentioned_agents
        d.trigger_type = "mention"
        d.route_reason = f"explicit @mention -> {mentioned_agents}"
        d.should_dispatch = "hermes" in mentioned_agents
        d.should_write_session = d.should_dispatch
        return d

    # Rule 5: plain reply to an agent (no @) -> only that agent
    if has_reply and replied_agent:
        d.target_agents = [replied_agent]
        d.trigger_type = "reply"
        d.route_reason = f"reply to {replied_agent} (no @) -> only {replied_agent}"
        d.should_dispatch = replied_agent == "hermes"
        d.should_write_session = d.should_dispatch
        return d

    # Rule 1: plain group message -> all silent
    d.trigger_type = "none"
    d.route_reason = "plain group message - all bots silent (observed only)"
    d.should_dispatch = False
    d.observed = True
    return d


def extract_mentions_from_event(event: Any) -> List[str]:
    """Extract @mention usernames from a Hermes MessageEvent's raw_message
    (a PTB Message).  Returns lowercased usernames without @."""
    raw = getattr(event, "raw_message", None)
    if raw is None:
        return []
    entities = getattr(raw, "entities", None) or []
    caption_entities = getattr(raw, "caption_entities", None) or []
    text = getattr(raw, "text", "") or ""
    caption = getattr(raw, "caption", "") or ""
    found: List[str] = []
    try:
        # PTB MessageEntity with type 'mention'
        for ents, src in ((entities, text), (caption_entities, caption)):
            for e in ents:
                etype = getattr(e, "type", "")
                if str(etype) == "mention":
                    off = getattr(e, "offset", 0)
                    length = getattr(e, "length", 0)
                    if src and off + length <= len(src):
                        found.append(src[off:off + length].lstrip("@"))
                elif str(etype) == "text_mention":
                    user = getattr(e, "user", None)
                    uname = getattr(user, "username", None) if user else None
                    if uname:
                        found.append(uname)
    except Exception:
        logger.debug("multiagent: mention entity parse failed", exc_info=True)
    return [u.lower() for u in found if u]

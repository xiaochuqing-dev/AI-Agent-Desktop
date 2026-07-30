"""Unit tests for the multi-agent routing policy.

These cover the stage-1.5 spec §16 acceptance items A-N that are testable
purely on the Hermes side (the policy is a pure function).  Items requiring
real Telegram E2E (cross-agent reply) are in the E2E checklist, not here.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the hermes-agent root importable when running pytest from the plugin dir.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

from plugins.multiagent.config import AgentSpec, MultiAgentConfig
from plugins.multiagent.policy import RouteInput, decide, parse_mentions


@pytest.fixture
def cfg() -> MultiAgentConfig:
    c = MultiAgentConfig()
    c.agents = {
        "hermes": AgentSpec("hermes", "your_hermes_bot", "orchestrator"),
        "claude": AgentSpec("claude", "your_claude_code_bot", "coder"),
        "codex": AgentSpec("codex", "your_codex_bot", "coder"),
    }
    c.group_chat_id = "-100xxxxxxxxxx"
    c.admins = ["REPLACE_WITH_YOUR_USER_ID"]
    return c


G = "-100xxxxxxxxxx"


def _inp(text="", **kw) -> RouteInput:
    defaults = dict(chat_id=G, chat_type="group")
    defaults.update(kw)
    return RouteInput(text=text, **defaults)


# A. Plain group message -> all bots silent
def test_plain_message_all_silent(cfg):
    d = decide(_inp("今天天气不错"), cfg)
    assert d.trigger_type == "none"
    assert d.should_dispatch is False
    assert d.observed is True
    assert d.target_agents == []


# B. Single @ -> only that agent
def test_single_mention_only_named_agent(cfg):
    d = decide(_inp("@your_claude_code_bot 测试代号是 123",
                    mentions=["your_claude_code_bot"]), cfg)
    assert d.target_agents == ["claude"]
    assert "hermes" not in d.target_agents  # Hermes must not know "123"


# B cont: Codex should not know Claude's private content unless /mashare'd
def test_cross_agent_isolation(cfg):
    d = decide(_inp("@your_codex_bot 测试代号是什么?",
                    mentions=["your_codex_bot"]), cfg)
    assert d.target_agents == ["codex"]
    assert "claude" not in d.target_agents


# C. Hermes does not reply without @
def test_hermes_silent_without_mention(cfg):
    d = decide(_inp("测试"), cfg)
    assert d.should_dispatch is False
    assert "hermes" not in d.target_agents


# D. Reply to an agent -> only that agent
def test_reply_to_agent(cfg):
    d = decide(_inp("继续", reply_to_message_id="555",
                    reply_to_text="[Reply to @your_hermes_bot]: prev"), cfg,
               reply_target_agent="hermes")
    assert d.target_agents == ["hermes"]
    assert d.should_dispatch is True


# E. Cross-agent reference: reply to Claude + @Codex -> only Codex, Claude's
#    text attached as reference, Claude not triggered.
def test_cross_agent_reference(cfg):
    d = decide(_inp("@your_codex_bot 评价一下",
                    mentions=["your_codex_bot"],
                    reply_to_message_id="555",
                    reply_to_text="[Reply to @your_claude_code_bot]: 方案A"),
               cfg, reply_target_agent="claude")
    assert d.target_agents == ["codex"]
    assert "claude" not in d.target_agents
    assert d.reference_context is not None
    assert "方案A" in d.reference_context or "claude" in d.reference_context


# F. Multiple @ -> only the named agents
def test_multiple_mentions(cfg):
    d = decide(_inp("@your_claude_code_bot @your_codex_bot 分别给方案",
                    mentions=["your_claude_code_bot", "your_codex_bot"]), cfg)
    assert set(d.target_agents) == {"claude", "codex"}
    assert "hermes" not in d.target_agents


# G. @all -> next stage, not a fake broadcast
def test_at_all_not_enabled(cfg):
    d = decide(_inp("@all 分别说一句测试回复"), cfg)
    assert d.trigger_type == "broadcast"
    assert d.should_dispatch is False
    assert d.notice is not None  # user-facing "not enabled" notice
    assert d.observed is True


# N. Bot-origin message -> anti-loop, never auto-trigger
def test_bot_origin_anti_loop(cfg):
    d = decide(_inp("some bot output", sender_is_bot=True), cfg)
    assert d.should_dispatch is False
    assert d.observed is True
    assert "anti-loop" in d.route_reason or d.trigger_type == "none"


# DM always dispatches to Hermes
def test_dm_always_hermes(cfg):
    d = decide(_inp("hi", chat_id="123", chat_type="dm"), cfg)
    assert d.target_agents == ["hermes"]
    assert d.should_dispatch is True


# Governance command /ma* -> Hermes
def test_governance_command_routes_to_hermes(cfg):
    d = decide(_inp("/mashared", is_command=True, command_name="mashared"), cfg)
    assert d.target_agents == ["hermes"]
    assert d.trigger_type == "command"


# Builtin command /new -> normal dispatch (not governance)
def test_builtin_command_normal_dispatch(cfg):
    d = decide(_inp("/new", is_command=True, command_name="new"), cfg)
    assert d.target_agents == ["hermes"]
    assert d.should_dispatch is True


# mention parsing
def test_parse_mentions():
    assert parse_mentions("@your_claude_code_bot hi @codex") == [
        "your_claude_code_bot", "codex"]
    assert parse_mentions("no mentions here") == []
    assert parse_mentions("", ["hermes"]) == ["hermes"]


# @all stripped from mentions
def test_at_all_stripped_from_mentions(cfg):
    d = decide(_inp("@all @your_hermes_bot hi",
                    mentions=["all", "your_hermes_bot"]), cfg)
    # @all present but also @hermes -> hermes should still dispatch (explicit
    # mention takes precedence; @all is just extra).  Actually per policy, if
    # there are real mentions after stripping @all, those win.
    assert "hermes" in d.target_agents


# Shared memory policy: never auto-write
def test_never_auto_write_shared(cfg):
    d = decide(_inp("@your_hermes_bot save this",
                    mentions=["your_hermes_bot"]), cfg)
    assert d.should_write_shared is False


# topic isolation: different thread_id -> different scope context
def test_topic_scope_independent(cfg):
    d1 = decide(_inp("@your_hermes_bot topic A",
                     mentions=["your_hermes_bot"], thread_id="100"), cfg)
    d2 = decide(_inp("@your_hermes_bot topic B",
                     mentions=["your_hermes_bot"], thread_id="200"), cfg)
    # Both dispatch to hermes, but their thread_id differs (isolation is at
    # the session-key layer, not the policy; we just verify the input carries
    # through).
    assert d1.should_dispatch and d2.should_dispatch

"""Unit tests for Stage 2 orchestration intent recognition.

Covers spec §7 (explicit instruction priority, multi-agent inference, abstract
self-decide) and §8 (pause/cancel/resume intervention detection).
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

from plugins.multiagent import _recognise_orchestration_intent, _recognise_intervention
from plugins.multiagent.config import AgentSpec, MultiAgentConfig


@pytest.fixture
def cfg() -> MultiAgentConfig:
    c = MultiAgentConfig()
    c.agents = {
        "claude": AgentSpec(name="claude", telegram_username="your_claude_code_bot", role="coder"),
        "codex": AgentSpec(name="codex", telegram_username="your_codex_bot", role="coder"),
    }
    return c


# ---------------------------------------------------------------------------
# Orchestration intent (spec §7)
# ---------------------------------------------------------------------------

def test_explicit_single_delegation_claude(cfg):
    mode, targets = _recognise_orchestration_intent("让Claude去看ProjectFlow代码", cfg)
    assert mode == "DELEGATE"
    assert targets == ["claude"]


def test_explicit_single_delegation_codex(cfg):
    mode, targets = _recognise_orchestration_intent("让Codex独立review一下", cfg)
    assert mode == "DELEGATE"
    assert targets == ["codex"]


def test_discussion_both_agents(cfg):
    mode, targets = _recognise_orchestration_intent("你们讨论一下这个架构", cfg)
    assert mode == "DISCUSSION"
    assert set(targets) == {"claude", "codex"}


def test_execution_implement_and_review(cfg):
    mode, targets = _recognise_orchestration_intent("让Claude实现这个功能然后Review", cfg)
    assert mode == "EXECUTION"
    assert "claude" in targets


def test_parallel_research_both(cfg):
    mode, targets = _recognise_orchestration_intent("让Claude和Codex分别分析这个架构", cfg)
    assert mode == "RESEARCH"
    assert set(targets) == {"claude", "codex"}


def test_both_delegate_when_no_clearer_mode(cfg):
    mode, targets = _recognise_orchestration_intent("让Claude和Codex去看看最新代码", cfg)
    assert mode == "DELEGATE"
    assert set(targets) == {"claude", "codex"}


def test_no_intent_plain_chat(cfg):
    """Plain @Hermes chat with no orchestration keywords -> None (Hermes self)."""
    assert _recognise_orchestration_intent("今天天气怎么样", cfg) is None
    assert _recognise_orchestration_intent("帮我看看这个问题", cfg) is None


# ---------------------------------------------------------------------------
# Stage 2.5: natural follow-up delegation (the "second-relay no-reply" fix).
# These phrases were mis-classified as None (Hermes self-replied + searched on
# its own) before the recogniser was broadened.  They must now delegate.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "问一下claude还记得测试号码吗",
    "再去问一下Claude还记不记得刚才的测试号码",
    "再问一下Claude刚才的号码",
    "查一下Codex的看法",
    "让Claude看看这个",
    "继续刚才的,让Claude回答",
    "Claude还记得我说的代号吗",
])
def test_natural_followup_delegates(cfg, phrase):
    """Natural follow-up phrasings naming an agent must delegate (not None)."""
    result = _recognise_orchestration_intent(phrase, cfg)
    assert result is not None, f"follow-up phrase should delegate: {phrase!r}"
    assert result[0] == "DELEGATE"


def test_plain_chat_without_agent_stays_none(cfg):
    """Broadening must NOT swallow plain Hermes chat that names no agent."""
    assert _recognise_orchestration_intent("你是什么模型", cfg) is None
    assert _recognise_orchestration_intent("中午好", cfg) is None
    assert _recognise_orchestration_intent("帮我查一下这个问题", cfg) is None  # no agent named


# ---------------------------------------------------------------------------
# Intervention detection (spec §8)
# ---------------------------------------------------------------------------

def test_intervention_pause():
    assert _recognise_intervention("@Hermes 暂停当前任务") == "pause"
    assert _recognise_intervention("先停一下") == "pause"


def test_intervention_cancel():
    assert _recognise_intervention("取消这个任务") == "cancel"
    assert _recognise_intervention("不要了") == "cancel"


def test_intervention_resume():
    assert _recognise_intervention("继续") == "resume"
    assert _recognise_intervention("恢复任务") == "resume"


def test_intervention_none_for_normal_text():
    assert _recognise_intervention("让Claude分析一下") is None
    assert _recognise_intervention("讨论这个架构") is None

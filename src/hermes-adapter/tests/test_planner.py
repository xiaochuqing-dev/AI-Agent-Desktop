"""Unit tests for the Stage 2.5 (追加) LLM semantic planner.

These use a fake ``llm_complete`` that returns canned JSON, so they verify the
planner's parsing/coercion/explicit-agent-override logic without a real model.
The 6 验收 phrases from 需求 §11 are covered.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

from plugins.multiagent._planner import (
    SemanticPlan, PlanTask, plan_with_llm, plan_from_keywords,
    _extract_json, _detect_detail_requested, plan_to_mode_targets,
)


# ---------------------------------------------------------------------------
# JSON extraction (robustness)
# ---------------------------------------------------------------------------

def test_extract_json_plain():
    assert _extract_json('{"action":"DELEGATE"}') == {"action": "DELEGATE"}


def test_extract_json_with_prose_around():
    text = '好的，这是计划：\n```json\n{"action":"DELEGATE","targets":["claude"]}\n```\n完成'
    assert _extract_json(text) == {"action": "DELEGATE", "targets": ["claude"]}


def test_extract_json_greedy_braces_with_narration():
    text = 'Let me think. {"action":"ANSWER_SELF","targets":[]} done.'
    assert _extract_json(text) == {"action": "ANSWER_SELF", "targets": []}


def test_extract_json_invalid_returns_none():
    assert _extract_json("not json at all") is None
    assert _extract_json("") is None
    assert _extract_json("{broken json") is None


# ---------------------------------------------------------------------------
# detail_requested detection
# ---------------------------------------------------------------------------

def test_detail_requested_detection():
    assert _detect_detail_requested("给我详细总结一下") is True
    assert _detect_detail_requested("展开讲讲") is True
    assert _detect_detail_requested("完整报告") is True
    assert _detect_detail_requested("逐条说明") is True
    assert _detect_detail_requested("详细复盘") is True
    assert _detect_detail_requested("总结一下") is False
    assert _detect_detail_requested("让Claude看看") is False


# ---------------------------------------------------------------------------
# plan_with_llm with a fake llm_complete
# ---------------------------------------------------------------------------

def _fake_llm(json_str: str):
    def _complete(system, user):
        return json_str
    return _complete


def test_plan_delegate_single_agent():
    raw = '{"action":"DELEGATE","targets":["claude"],"continuation":false,"constraints":""}'
    plan = plan_with_llm("给Claude看看这个问题", "", _fake_llm(raw))
    assert plan is not None
    assert plan.action == "DELEGATE"
    assert plan.targets == ["claude"]
    assert plan.mode_for_orchestrator() == "DELEGATE"


def test_plan_answer_self():
    raw = '{"action":"ANSWER_SELF","targets":[],"constraints":"不要叫Claude和Codex"}'
    plan = plan_with_llm("你自己回答，不要叫Claude和Codex", "", _fake_llm(raw))
    assert plan is not None
    assert plan.action == "ANSWER_SELF"
    assert plan.targets == []
    assert plan.mode_for_orchestrator() is None  # no orchestration


def test_plan_explicit_agent_assignment_preserved():
    """需求 §5: user assigns A->codex, B->claude; planner must NOT swap."""
    raw = ('{"action":"DELEGATE","targets":["codex","claude"],'
           '"tasks":[{"label":"A","goal":"分析原因","agent":"codex","depends_on":[]},'
           '{"label":"B","goal":"看GitHub最新代码","agent":"claude","depends_on":[]}],'
           '"constraints":"只给方案不要改代码"}')
    plan = plan_with_llm("A让Codex分析，B让Claude去GitHub查", "", _fake_llm(raw))
    assert plan is not None
    assert len(plan.tasks) == 2
    # Explicit assignment preserved: A->codex, B->claude (not swapped).
    assert plan.tasks[0].agent == "codex"
    assert plan.tasks[1].agent == "claude"
    assert plan.tasks[0].label == "A"
    assert "不要改代码" in plan.constraints


def test_plan_discuss_both_agents():
    raw = '{"action":"DISCUSS","targets":["claude","codex"],"continuation":false}'
    plan = plan_with_llm("两边完成后再讨论", "", _fake_llm(raw))
    assert plan is not None
    assert plan.action == "DISCUSS"
    assert set(plan.targets) == {"claude", "codex"}
    assert plan.mode_for_orchestrator() == "DISCUSSION"


def test_plan_parallel_research():
    raw = '{"action":"PARALLEL","targets":["claude","codex"]}'
    plan = plan_with_llm("让两边分别独立分析", "", _fake_llm(raw))
    assert plan is not None
    assert plan.action == "PARALLEL"
    # PARALLEL 现映射到 DELEGATE（走 _run_delegate 的 dual_agent 并行分支，
    # 而非 RESEARCH 串行讨论）。plan.action 仍是 PARALLEL，由 _run_delegate 分流。
    assert plan.mode_for_orchestrator() == "DELEGATE"


def test_discuss_still_maps_to_discussion():
    """只有真讨论才进 DISCUSSION 模式，防止并行/顺序误判为讨论。"""
    raw = '{"action":"DISCUSS","targets":["claude","codex"]}'
    plan = plan_with_llm("让两边讨论一下", "", _fake_llm(raw))
    assert plan is not None
    assert plan.action == "DISCUSS"
    assert plan.mode_for_orchestrator() == "DISCUSSION"


def test_plan_continuation_followup():
    raw = '{"action":"DELEGATE","targets":["claude"],"continuation":true}'
    plan = plan_with_llm("叫Claude接着刚才那个继续弄", "", _fake_llm(raw))
    assert plan is not None
    assert plan.continuation is True


def test_plan_detail_requested_from_json():
    raw = '{"action":"DELEGATE","targets":["claude"],"detail_requested":true}'
    plan = plan_with_llm("让Claude分析然后详细总结", "", _fake_llm(raw))
    assert plan is not None
    assert plan.detail_requested is True


def test_plan_detail_requested_from_text_when_json_omits():
    raw = '{"action":"DELEGATE","targets":["claude"]}'
    plan = plan_with_llm("让Claude分析，然后给我详细总结", "", _fake_llm(raw))
    assert plan is not None
    # Even though JSON omitted detail_requested, the text scan catches it.
    assert plan.detail_requested is True


def test_plan_clarify():
    raw = '{"action":"CLARIFY","targets":[]}'
    plan = plan_with_llm("嗯...", "", _fake_llm(raw))
    assert plan is not None
    assert plan.action == "CLARIFY"
    assert plan.mode_for_orchestrator() is None


def test_plan_invalid_action_returns_none():
    raw = '{"action":"FLY","targets":["claude"]}'
    plan = plan_with_llm("whatever", "", _fake_llm(raw))
    assert plan is None  # invalid -> fallback signal


def test_plan_no_llm_returns_none():
    assert plan_with_llm("让Claude看看", "", None) is None


def test_plan_llm_raises_returns_none():
    def bad(system, user):
        raise RuntimeError("boom")
    assert plan_with_llm("让Claude看看", "", bad) is None


def test_plan_llm_empty_returns_none():
    assert plan_with_llm("让Claude看看", "", _fake_llm("")) is None


def test_plan_unparseable_returns_none():
    assert plan_with_llm("让Claude看看", "", _fake_llm("这不是JSON")) is None


def test_plan_both_target_expands():
    raw = '{"action":"DELEGATE","targets":["both"]}'
    plan = plan_with_llm("让两边都看看", "", _fake_llm(raw))
    assert plan is not None
    assert set(plan.targets) == {"claude", "codex"}


def test_plan_default_target_when_missing():
    # action needs an agent but targets omitted -> defaults to claude.
    raw = '{"action":"DELEGATE"}'
    plan = plan_with_llm("给Claude看看", "", _fake_llm(raw))
    assert plan is not None
    assert plan.targets == ["claude"]


# ---------------------------------------------------------------------------
# fast-path (deterministic, 100%-reliable only)
# ---------------------------------------------------------------------------

def test_fast_path_execution_with_agent():
    plan = plan_from_keywords("让Claude实现这个功能")
    assert plan is not None
    assert plan.action == "EXECUTE"
    assert "claude" in plan.targets


def test_fast_path_misses_generic_phrase():
    """需求 §6: fast-path not matching != not a delegation."""
    assert plan_from_keywords("给Claude看看这个问题") is None
    assert plan_from_keywords("把这个问题丢给Codex判断") is None


def test_fast_path_no_agent_no_match():
    assert plan_from_keywords("帮我实现一下") is None


# ---------------------------------------------------------------------------
# plan_to_mode_targets mapping
# ---------------------------------------------------------------------------

def test_plan_to_mode_targets_delegates():
    plan = SemanticPlan(action="DELEGATE", targets=["claude"])
    assert plan_to_mode_targets(plan) == ("DELEGATE", ["claude"])


def test_plan_to_mode_targets_answer_self_is_none():
    plan = SemanticPlan(action="ANSWER_SELF", targets=[])
    assert plan_to_mode_targets(plan) is None


def test_plan_to_mode_targets_clarify_is_none():
    plan = SemanticPlan(action="CLARIFY", targets=[])
    assert plan_to_mode_targets(plan) is None

"""Stage 2.5 (追加) - Hermes 语义调度规划器.

Replaces the keyword-driven intent recogniser as the PRIMARY path for deciding
what an @Hermes message means.  Per the追加修订要求:

  * 硬路由只负责"消息交给谁" (@Claude/@Codex/@Hermes/Reply+@) - kept in
    policy.py, untouched.
  * 一旦消息进入 Hermes, 让 Hermes 当前大模型整段理解用户意图, 输出结构化
    计划, 而不是靠不断扩充中文动词表.
  * 关键词规则只保留极少 100% 可靠的 fast-path; 没命中 != 不是委派, 也不 !=
    Hermes 自己回答 -> 交给 LLM.

The planner asks the host-owned LLM (ctx.llm, no trust-override config needed)
for a strict JSON plan and parses it robustly (whole-string -> regex {…} ->
json.loads, tolerating narration around the JSON, mirroring the xai provider
extractor pattern).  On any failure it returns None so the caller falls back to
the legacy keyword recogniser (kept as a safety net for no-LLM / test envs).

Explicit user agent assignment is binding (需求 §5): the system prompt forbids
the planner from swapping a user-named agent for a "better" one.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 探针：确认 gateway 实际加载的是这个文件。import 时写标记文件。
try:
    with open(r"C:\Users\<WINDOWS_USER>\AppData\Local\hermes\_planner_probe.txt", "w", encoding="utf-8") as _pf:
        _pf.write("loaded _planner.py from " + __file__ + "\n")
        _pf.write("PARALLEL maps to DELEGATE (new version)\n")
except Exception:
    pass

# Valid action values the planner may emit.
VALID_ACTIONS = ("ANSWER_SELF", "DELEGATE", "PARALLEL", "DISCUSS", "EXECUTE", "CLARIFY")
VALID_TARGETS = ("claude", "codex", "both", "self")

# Greedy {…} match: first '{' to last '}', tolerating prose around it.
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


@dataclass
class PlanTask:
    """One sub-task within a multi-step plan (需求 §3: 目标/分配/顺序/依赖/并行/限制)."""
    goal: str = ""
    agent: str = ""          # claude | codex | both
    depends_on: List[str] = field(default_factory=list)  # names/ids of prior tasks
    allow_write: Optional[bool] = None  # None = unspecified (respect agent mode)
    label: str = ""          # short id like "A"/"B" for depends_on refs


@dataclass
class SemanticPlan:
    """Hermes' structured understanding of one @Hermes message."""
    action: str              # one of VALID_ACTIONS
    targets: List[str]       # resolved agent list: subset of [claude, codex] (or [] for self)
    tasks: List[PlanTask] = field(default_factory=list)
    continuation: bool = False   # is this a follow-up of recent work?
    constraints: str = ""        # free-text user constraints ("不要改代码", "只给方案")
    detail_requested: bool = False  # user asked for detailed/expanded summary
    raw: str = ""                # original user text (for audit / fallback)

    def mode_for_orchestrator(self) -> Optional[str]:
        """Map the planner action to the orchestrator's mode vocabulary.
        Returns None for ANSWER_SELF/CLARIFY (no orchestration).

        注：PARALLEL 映射到 DELEGATE（不是 RESEARCH），因为并行执行的逻辑在
        _run_delegate 里按 action==PARALLEL 分流到 dual_agent.run_parallel。
        RESEARCH 模式（_run_discussion 串行讨论）保留给 DISCUSS 之外的旧路径。"""
        return {
            "DELEGATE": "DELEGATE",
            "PARALLEL": "DELEGATE",     # 并行独立分析 -> 走 _run_delegate 的并行分支
            "DISCUSS": "DISCUSSION",
            "EXECUTE": "EXECUTION",
        }.get(self.action)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Robustly extract a JSON object from an LLM response that may have
    narration / code fences around it.  Mirrors plugins/web/xai/provider.py.
    Returns the parsed dict or None."""
    if not text:
        return None
    # 1. Try the whole string (model obeyed "only JSON").
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    # 2. Strip a ```json ... ``` fence first, then parse inside.
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        try:
            obj = json.loads(fence.group(1))
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
    # 3. Greedy first-{ to last-} (tolerates leading/trailing prose).
    m = _JSON_BLOCK_RE.search(text)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
    return None


_SYSTEM_PROMPT = (
    "你是 Hermes，一个 Telegram 群里多 Agent 协作的主持人。用户刚 @ 了你对一条消息做调度决策。\n"
    "你的任务：完整理解整段用户消息的自然语言意图，输出一个严格的 JSON 计划。不要把消息按关键词切碎。\n\n"
    "可用的 Agent：claude（Claude Code，代码/工具/分析/执行）、codex（Codex，分析/Review/执行）。\n"
    "你自己（hermes）也能直接回答，不需要调度其他 Agent。\n\n"
    "决策原则：\n"
    "1. 如果用户只是和你聊天、问你的看法、或明确说“你自己回答/不要叫Claude和Codex” -> action=ANSWER_SELF。\n"
    "2. 让某个 Agent 做事（给/丢/叫/让/问/查/看/确认/判断/过一眼/接着弄…）且只涉及一个 Agent，或多个 Agent 各做各的独立任务 -> DELEGATE（单 Agent）或 PARALLEL（多 Agent 各自独立、互不评价）。\n"
    "3. 用户表达出“先后顺序”时（无论用什么措辞：先…再…、然后、完成后、接着、基于上一步结果、把A的结果交给B、按顺序执行、第一步…第二步…等任何体现前后依赖关系的语义） -> action=DELEGATE，targets=[A,B]，tasks 必须填两步：第一步 agent=A，第二步 agent=B 且 depends_on=[第一步的label]。第二步的 goal 只写 B 自己要做的事，不要写“审查/基于A”等跨 Agent 指令（系统会自动把 A 的真实输出注入 B 的上下文，不需要你在 goal 里转述）。\n"
    "4. 【关键边界】只有用户明确要求“讨论/商量/辩论/互相审查/反驳对方/达成共识/对比观点”时才用 DISCUSS。\n"
    "   - “让 A 查时间，同时让 B 查 CPU”是 PARALLEL（独立并行），不是讨论。\n"
    "   - “先让 A 查，再让 B 基于结果继续”是 DELEGATE 顺序，不是讨论。\n"
    "   - 不要因为涉及两个 Agent 就当成讨论。\n"
    "5. 用户实现/修改代码 + Review（无论是否同两个 Agent）-> EXECUTE。\n"
    "6. 消息提到“刚才/继续/接着/还记得/上一轮” -> continuation=true。\n"
    "7. 用户明确指定某 Agent（“任务A给Codex，B给Claude”）必须严格服从，不得擅自交换。Explicit user intent overrides planner choice.\n"
    "8. 只有存在重大歧义才用 CLARIFY；能合理推断就不要澄清。\n"
    "9. 用户限制“不要改代码/只给方案/只分析”等 -> 写入 constraints。\n"
    "10. 用户明确要求“详细总结/展开讲/完整报告/逐条说明/详细复盘” -> detail_requested=true；否则 false。\n"
    "11. 【强制】当 targets 含两个或以上 Agent 时，tasks 字段绝不能为空数组也不能省略，必须为每个 Agent 填一个 task。否则系统会错误地把顺序任务退化为并行（用户要的是顺序，却变成并行执行，前步结果无法传给后步）。PARALLEL 时每个 task 独立 depends_on 为空；顺序 DELEGATE 时第二步 depends_on 第一步。\n\n"
    "输出格式（只输出 JSON，不要多余解释）：\n"
    "{\n"
    "  \"action\": \"ANSWER_SELF|DELEGATE|PARALLEL|DISCUSS|EXECUTE|CLARIFY\",\n"
    "  \"targets\": [\"claude\"],\n"
    "  \"tasks\": [{\"label\": \"A\", \"goal\": \"...\", \"agent\": \"claude\", \"depends_on\": [], \"allow_write\": false}],\n"
    "  \"continuation\": false,\n"
    "  \"constraints\": \"\",\n"
    "  \"detail_requested\": false\n"
    "}\n"
    "字段说明：\n"
    "- action: 必填。\n"
    "- targets: 被 action 涉及的 Agent 列表，取值 claude/codex（ANSWER_SELF/CLARIFY 时可为空数组）。\n"
    "- tasks: 只要 targets 含多个 Agent 就必填且不能为空。每个 Agent 一个 task，goal 只描述该 Agent 自己要做什么，绝对不要在 goal 里写“再让另一个 Agent 做 X”或“交给 Codex 审查”这类跨 Agent 指令--否则该 Agent 会在群里公开当主持人。PARALLEL 时每个 task 独立 depends_on 为空；顺序 DELEGATE 时按用户指定顺序填，第二步 depends_on 第一步，且第二步 goal 不要含“审查/请审查”只写它自己要做的检查。\n"
    "- continuation/约束/detail_requested 按上面原则填。"
)


def _detect_detail_requested(text: str) -> bool:
    """Cheap pre-scan for explicit detail requests (also enforced by the LLM,
    but deterministic so it works even if the planner is skipped/falls back)."""
    low = (text or "").lower()
    return any(k in low for k in (
        "详细总结", "展开讲", "展开说", "完整报告", "逐条说明", "逐条",
        "详细复盘", "详细说明", "详细分析", "详述",
    ))


def plan_with_llm(text: str, recent_context: str,
                  llm_complete: Optional[Callable[[str, str], str]]
                  ) -> Optional[SemanticPlan]:
    """Ask the host-owned LLM to understand the whole @Hermes message and
    return a structured plan.  Returns None on any failure (no LLM, parse
    error, invalid action) so the caller can fall back to the keyword path."""
    if llm_complete is None:
        return None
    if not (text or "").strip():
        return None
    user_prompt = (
        f"【最近群聊上下文（可能为空）】\n{recent_context[:1500]}\n\n"
        f"【用户这条 @Hermes 消息（需你整段理解）】\n{text[:2000]}\n\n"
        f"请输出 JSON 计划。"
    )
    try:
        raw = llm_complete(_SYSTEM_PROMPT, user_prompt)
    except Exception:
        logger.exception("planner: llm_complete raised; returning None for fallback")
        return None
    if not raw or not raw.strip():
        logger.warning("planner: LLM 返回空响应")
        return None
    # 记录 LLM 原始响应（截断），便于诊断 tasks 是否生成
    logger.info("planner: LLM 原始响应: %s", raw[:500])
    obj = _extract_json(raw)
    if obj is None:
        logger.warning("planner: could not parse JSON from LLM response: %s", raw[:200])
        return None
    plan = _coerce_plan(obj, text)
    if plan is not None:
        # 记录解析后的 plan，重点看 tasks 是否生成
        logger.info(
            "planner: 解析后 plan action=%s targets=%s tasks=%d cont=%s",
            plan.action, plan.targets, len(plan.tasks), plan.continuation,
        )
        for i, t in enumerate(plan.tasks):
            logger.info(
                "planner: task[%d] label=%s agent=%s goal=%s depends_on=%s",
                i, t.label, t.agent, t.goal[:80], t.depends_on,
            )
    return plan


def _coerce_plan(obj: Dict[str, Any], text: str) -> Optional[SemanticPlan]:
    """Validate + coerce the parsed dict into a SemanticPlan.  Returns None if
    the action is missing/invalid (so the caller falls back)."""
    action = str(obj.get("action", "")).strip().upper()
    if action not in VALID_ACTIONS:
        logger.warning("planner: invalid action %r", action)
        return None
    # Resolve targets -> concrete agent list.
    raw_targets = obj.get("targets", []) or []
    if isinstance(raw_targets, str):
        raw_targets = [raw_targets]
    targets = _resolve_targets(raw_targets, action)
    # Parse tasks (optional).
    tasks: List[PlanTask] = []
    for t in (obj.get("tasks") or []):
        if not isinstance(t, dict):
            continue
        agent = str(t.get("agent", "")).strip().lower()
        if agent == "both":
            agent = "both"
        tasks.append(PlanTask(
            goal=str(t.get("goal", ""))[:500],
            agent=agent if agent in ("claude", "codex", "both") else "",
            depends_on=[str(x) for x in (t.get("depends_on") or [])],
            allow_write=t.get("allow_write") if isinstance(t.get("allow_write"), bool) else None,
            label=str(t.get("label", ""))[:8],
        ))
    return SemanticPlan(
        action=action,
        targets=targets,
        tasks=tasks,
        continuation=bool(obj.get("continuation", False)),
        constraints=str(obj.get("constraints", ""))[:500],
        detail_requested=bool(obj.get("detail_requested", False)) or _detect_detail_requested(text),
        raw=text,
    )


def _resolve_targets(raw_targets: List[Any], action: str) -> List[str]:
    """Turn the planner's targets into a concrete [claude|codex] list.
    ANSWER_SELF/CLARIFY -> []. 'both' -> [claude, codex]."""
    if action in ("ANSWER_SELF", "CLARIFY"):
        return []
    seen: List[str] = []
    for t in raw_targets:
        s = str(t).strip().lower()
        if s == "both":
            for a in ("claude", "codex"):
                if a not in seen:
                    seen.append(a)
        elif s in ("claude", "codex") and s not in seen:
            seen.append(s)
    # Default: if action needs an agent but none named, pick claude.
    if action in ("DELEGATE", "PARALLEL", "DISCUSS", "EXECUTE") and not seen:
        seen = ["claude"]
    return seen


# ---------------------------------------------------------------------------
# Fast-path: only 100%-reliable, deterministic signals (需求 §6).
# ---------------------------------------------------------------------------

def plan_from_keywords(text: str) -> Optional[SemanticPlan]:
    """A tiny deterministic fast-path for cases that are unambiguous and should
    NOT wait for an LLM round-trip.  Per需求 §6: this NOT matching does NOT
    mean "not a delegation" - it just means "let the LLM decide".

    Currently only catches explicit code-modification intent (EXECUTION) with a
    named agent, since that has a hard two-round review-rework semantic that we
    want to guarantee without depending on the LLM.
    """
    low = (text or "").lower()
    has_claude = "claude" in low
    has_codex = "codex" in low
    if any(k in low for k in ("实现", "修改", "改代码", "编码", "写代码", "重构")):
        if has_claude or has_codex:
            targets = []
            if has_claude:
                targets.append("claude")
            if has_codex:
                targets.append("codex")
            return SemanticPlan(
                action="EXECUTE", targets=targets or ["claude"],
                detail_requested=_detect_detail_requested(text), raw=text,
            )
    return None


# ---------------------------------------------------------------------------
# Orchestrator mode/targets mapping helper.
# ---------------------------------------------------------------------------

def plan_to_mode_targets(plan: SemanticPlan) -> Optional[Tuple[str, List[str]]]:
    """Map a plan to (orchestrator_mode, targets) for _start_orchestration.
    Returns None for ANSWER_SELF/CLARIFY (no orchestration)."""
    mode = plan.mode_for_orchestrator()
    if mode is None:
        return None
    return mode, plan.targets

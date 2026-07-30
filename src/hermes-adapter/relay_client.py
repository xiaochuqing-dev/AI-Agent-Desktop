"""Stage 2 relay client - the thin Hermes -> Claude/Codex execution channel.

Wraps cc-connect's synchronous relay RPC (``cc-connect relay send``) so the
Hermes orchestrator can delegate a bounded subtask to Claude or Codex and get
the full reply back.  This is the agents-as-tools runtime: Hermes keeps control
and integrates the returned ``final_output`` (mirrors OpenAI ``Agent.as_tool()``
and LangGraph supervisor ``output_mode="last_message"`` - intermediate tool
calls never enter Hermes' context).

Task-session isolation (constraint #2) -- SOFTENED in Stage 2.5
--------------------------------------------------------------
Natural continuity over perfect isolation.  The relay ``from_project`` is no
longer ``hermes-task_{task_id}`` (which changed every delegation and forced a
brand-new Claude/Codex session -> the "follow-up amnesia" the user hit).  It is
now a STABLE conversation key per (chat, agent, epoch):

  from_project = "hermes-conv_{chatID}_{agentID}_{epoch}"

so cc-connect derives ``relaySessionKey = relay:hermes-conv_{chat}_{agent}_{epoch}:...
``.  Within an epoch every delegation (new task_id or follow-up) reuses the same
Claude/Codex conversation.  Only an explicit /manew bumps the epoch to force a
fresh session.  ``task_id`` is retained for audit/trace/Review-count but no
longer drives session isolation.

binding is looked up by the *source* SessionKey's chatID (independent of
fromProject), so one /bind per group covers all tasks.

Hop guard (constraint correction #2)
------------------------------------
This does NOT block "an agent called once per task".  Normal multi-turn
discussion may call the same agent many times.  Instead it tracks, per task:

  * hop_count        - monotonic; orchestrator caps via max_hops fuse
  * speaker_sequence - detect A->B->A->B ping-pong (raised as a flag, not hard
                       block; orchestrator's Progress Ledger decides)
  * last_outputs     - detect consecutive near-identical content (stall signal)
  * idempotency      - relay requests carry an idempotency_key

The guard returns a :class:`HopGuard` snapshot; the orchestrator (Magentic-One
Progress Ledger / rework loop) decides whether to continue, not this client.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# cc-connect binary.  Resolved lazily so the module imports in tests without a
# real install.  We use the .exe directly (NOT the npm .cmd wrapper) because
# run.js re-downloads the official binary when `--version` doesn't match,
# which would overwrite our patched build.
_CC_CONNECT_BIN = os.path.join(
    os.environ.get("APPDATA", ""),
    "npm", "node_modules", "cc-connect", "bin", "cc-connect.exe",
)


def _resolve_cc_connect_bin() -> str:
    """Locate the cc-connect binary, honouring an env override for tests."""
    override = os.environ.get("CC_CONNECT_BIN", "").strip()
    if override:
        return override
    return _CC_CONNECT_BIN


# ---------------------------------------------------------------------------
# Hop guard snapshot
# ---------------------------------------------------------------------------

@dataclass
class HopGuard:
    """Per-task loop/stall signals surfaced to the orchestrator.

    None of these hard-block a relay; the orchestrator's convergence logic
    (Progress Ledger for discussion, rework cap for execution) decides.  This
    keeps normal, information-bearing discussion going (constraint #6) while
    giving the fuse the signals it needs.
    """
    hop_count: int = 0
    speaker_sequence: List[str] = field(default_factory=list)
    ping_pong_detected: bool = False
    last_output_hash: Optional[str] = None
    consecutive_repeat: int = 0

    def would_exceed_max_hops(self, max_hops: int) -> bool:
        return self.hop_count >= max_hops


def _hash_text(text: str) -> str:
    return hashlib.md5((text or "").strip().lower().encode("utf-8", "replace")).hexdigest()[:12]


def _is_ping_pong(seq: List[str]) -> bool:
    """True if the last 4+ speakers form an A<->B alternation with no third
    voice (a classic bot ping-pong).  Length 4 = two full A-B-A-B cycles."""
    if len(seq) < 4:
        return False
    tail = seq[-4:]
    return tail[0] == tail[2] and tail[1] == tail[3] and tail[0] != tail[1]


# ---------------------------------------------------------------------------
# Relay client
# ---------------------------------------------------------------------------

class RelayClient:
    """Synchronous Hermes -> Claude/Codex channel via cc-connect relay.

    Thread-safety: one instance per orchestrator task; the per-task guard
    state is guarded by a lock so a background orchestrator thread and a
    cancel/intervention check don't race.
    """

    def __init__(self, store: Any, chat_id: str, task_id: str,
                 cc_bin: Optional[str] = None, default_timeout: int = 600):
        # 600s matches cc-connect's [relay] timeout_secs.  Claude/Codex in
        # plan/suggest + high-reasoning mode (especially first spawn) can take
        # several minutes; 180s was too short and caused silent relay timeouts.
        self._store = store
        self._chat_id = str(chat_id)
        self._task_id = task_id  # retained for audit/trace; NOT for isolation
        self._cc_bin = cc_bin or _resolve_cc_connect_bin()
        self._default_timeout = default_timeout
        self._guard = HopGuard()
        self._lock = threading.Lock()
        # Source session key passed to cc-connect relay.  Stable per chat so the
        # relay manager can resolve the group binding; the actual Claude/Codex
        # conversation isolation is driven by from_project (see _from_project).
        self._session_key = f"telegram:{self._chat_id}:0"

    def _from_project(self, agent_id: str) -> str:
        """Stable per-(chat, agent, epoch) relay source project.

        Within an epoch every delegation reuses the same Claude/Codex
        conversation (natural follow-up continuity).  /manew bumps the epoch
        (via store.bump_relay_conversation_epoch) to force a fresh session.
        task_id is intentionally NOT embedded here -- that was the cause of
        follow-up amnesia (each @Hermes -> new task_id -> new agent session).
        """
        epoch = 0
        if self._store is not None:
            try:
                epoch = self._store.relay_conversation_epoch(self._chat_id, agent_id)
            except Exception:
                logger.exception("relay_client: failed to read relay epoch; using 0")
        return f"hermes-conv_{self._chat_id}_{agent_id}_{epoch}"

    # -- public ---------------------------------------------------------

    @property
    def guard(self) -> HopGuard:
        with self._lock:
            return HopGuard(
                hop_count=self._guard.hop_count,
                speaker_sequence=list(self._guard.speaker_sequence),
                ping_pong_detected=self._guard.ping_pong_detected,
                last_output_hash=self._guard.last_output_hash,
                consecutive_repeat=self._guard.consecutive_repeat,
            )

    def relay_session_key(self, agent_id: str = "claude") -> str:
        """The cc-connect-derived session key for this (chat, agent, epoch)
        (audit/verify).  Stable across task_ids within the same epoch."""
        return f"relay:{self._from_project(agent_id)}:telegram:{self._chat_id}"

    def send(self, to_project: str, agent_id: str, message: str,
             turn: int = 0, timeout: Optional[int] = None) -> Tuple[bool, str]:
        """Delegate to ``to_project`` and return ``(ok, reply_text)``.

        ``to_project`` is the cc-connect project name (claude-expert/codex-expert);
        ``agent_id`` is the short label (claude/codex) for the guard + audit +
        stable conversation key.  On failure returns ``(False, error_message)``.
        """
        timeout = timeout if timeout is not None else self._default_timeout
        # Update guard BEFORE the call so hop_count reflects this hop.
        with self._lock:
            self._guard.hop_count += 1
            self._guard.speaker_sequence.append(agent_id)
            self._guard.ping_pong_detected = _is_ping_pong(self._guard.speaker_sequence)

        from_project = self._from_project(agent_id)
        cmd = [
            self._cc_bin, "relay", "send",
            "--from", from_project,
            "--to", to_project,
            "--session-key", self._session_key,
            "--message", message,
        ]
        logger.info(
            "relay_client: send task=%s to=%s turn=%d hop=%d pingpong=%s conv=%s",
            self._task_id, to_project, turn, self._guard.hop_count,
            self._guard.ping_pong_detected, from_project,
        )
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace",
                # A1 黑窗修复：Hermes gateway 由 pythonw（无控制台）启动，
                # 直接 subprocess.run 一个 console 子系统程序（cc-connect.exe），
                # Windows 会为它新建可见控制台 -> 每次委派闪一个黑窗。
                # CREATE_NO_WINDOW (0x08000000) 让子进程无窗口运行，relay send
                # 本就是无交互的短命令（POST 到 daemon socket 即退），隐藏无副作用。
                # 注：这只挡 relay send 这一层；daemon 内部 spawn claude.exe/codex.exe
                # 的滞留窗由 cc_connect_autostart.py 的隐藏控制台宿主解决（A2）。
                creationflags=0x08000000,
            )
        except subprocess.TimeoutExpired:
            return False, f"relay timeout after {timeout}s (agent process not killed)"
        except FileNotFoundError:
            return False, f"cc-connect binary not found: {self._cc_bin}"
        except Exception as exc:
            return False, f"relay invocation failed: {exc}"

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            return False, f"relay exit {proc.returncode}: {err[:500]}"

        reply = (proc.stdout or "").strip()

        # Record the task_agent_session association (constraint #2 audit).
        try:
            self._store.record_task_agent_session(
                self._task_id, agent_id, self.relay_session_key(agent_id), turn,
            )
        except Exception:
            logger.exception("relay_client: failed to record task_agent_session")

        # Update guard with the reply content for repeat detection.
        with self._lock:
            h = _hash_text(reply)
            if h == self._guard.last_output_hash:
                self._guard.consecutive_repeat += 1
            else:
                self._guard.consecutive_repeat = 0
                self._guard.last_output_hash = h

        return True, reply

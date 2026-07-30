"""Shared cross-process SQLite store for the multi-agent group governance layer.

This DB is the single shared state between the three bot processes:

  * Hermes (this hermes-agent gateway)  -> writes via :class:`MultiAgentStore`
  * Claude Bot (cc-connect)             -> writes via the HTTP hook receiver
  * Codex Bot  (cc-connect)             -> writes via the HTTP hook receiver

It lives at ``<HERMES_HOME>/multiagent.db`` and uses WAL mode (concurrent
readers + one writer) exactly like ``state.db``.  The connection pattern is
mirrored from ``hermes_state.SessionDB`` (``check_same_thread=False``,
``isolation_level=None``, explicit ``BEGIN IMMEDIATE``, application-level
retry with jitter).

Reliability semantics
---------------------
The cc-connect ``[[hooks]]`` notification path is **best-effort / fire-and-forget**:
cc-connect fires the hook and discards the handler's response.  Therefore the
Transcript rows contributed by Claude/Codex are *best-effort*: if the HTTP
receiver is down or the write fails after retries, that message is simply not
recorded.  The store itself is durable (WAL + fsync on commit), but the
*data pipeline* feeding it from cc-connect is not guaranteed.  See the stage
report for the honest 🟡 marking on Transcript completeness.

Tables
------
  transcript        full group message flow (all 3 bots, in + out)
  shared_memory     explicitly-shared public facts (only via /mashare)
  route_log         per-message routing decision audit trail
  task_envelope     task identity / call-chain / loop-guard data model
  idempotency       dedup of processed (chat_id, msg_id) / update_ids
  msgid_agent_map   msg_id -> agent_id, for audit / Studio / long-term tracking
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS transcript (
    msg_id          TEXT NOT NULL,
    platform        TEXT NOT NULL,
    chat_id         TEXT NOT NULL,
    thread_id       TEXT,
    sender_type     TEXT NOT NULL,   -- human | bot
    sender_id       TEXT,
    sender_name     TEXT,
    agent_id        TEXT NOT NULL,   -- human | hermes | claude | codex
    text            TEXT,
    reply_to_msg_id TEXT,
    task_id         TEXT,
    trace_id        TEXT,
    trigger_type    TEXT,            -- command|mention|reply|broadcast|relay|orchestrator
    route_reason    TEXT,
    observed        INTEGER NOT NULL DEFAULT 0,
    has_images      INTEGER NOT NULL DEFAULT 0,
    has_files       INTEGER NOT NULL DEFAULT 0,
    has_audio       INTEGER NOT NULL DEFAULT 0,
    ts              TEXT NOT NULL,
    PRIMARY KEY (chat_id, msg_id)
);

CREATE TABLE IF NOT EXISTS shared_memory (
    memory_id           TEXT PRIMARY KEY,
    scope_type          TEXT NOT NULL,   -- group|topic|project|user_global
    scope_id            TEXT NOT NULL,
    content             TEXT NOT NULL,
    source_msg_id       TEXT,
    created_by          TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active',  -- active|superseded|deleted
    supersedes_id       TEXT,
    replaced_by_id      TEXT,
    version             INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS route_log (
    trace_id        TEXT NOT NULL,
    msg_id          TEXT,
    target_agent    TEXT,
    trigger_type    TEXT,
    route_reason    TEXT,
    wrote_session   INTEGER NOT NULL DEFAULT 0,
    wrote_shared    INTEGER NOT NULL DEFAULT 0,
    ts              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_envelope (
    task_id             TEXT PRIMARY KEY,
    context_id          TEXT,
    turn_id             TEXT,
    trace_id            TEXT,
    source              TEXT,
    target_agents       TEXT,   -- JSON list
    trigger_type        TEXT,
    reply_to_msg_id     TEXT,
    reference_msg_ids   TEXT,   -- JSON list
    reference_task_ids  TEXT,   -- JSON list
    memory_policy       TEXT,   -- JSON
    status              TEXT NOT NULL DEFAULT 'pending',
    idempotency_key     TEXT UNIQUE,
    hop_count           INTEGER NOT NULL DEFAULT 0,
    max_hops            INTEGER NOT NULL DEFAULT 0,
    ts                  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency (
    idempotency_key TEXT PRIMARY KEY,
    processed_at    TEXT NOT NULL,
    action          TEXT,
    result_hash     TEXT
);

CREATE TABLE IF NOT EXISTS msgid_agent_map (
    chat_id     TEXT NOT NULL,
    msg_id      TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    text_preview TEXT,
    ts          TEXT NOT NULL,
    PRIMARY KEY (chat_id, msg_id)
);

CREATE INDEX IF NOT EXISTS idx_transcript_chat_ts ON transcript(chat_id, ts);
CREATE INDEX IF NOT EXISTS idx_transcript_agent ON transcript(agent_id, ts);
CREATE INDEX IF NOT EXISTS idx_transcript_reply ON transcript(chat_id, reply_to_msg_id);
CREATE INDEX IF NOT EXISTS idx_shared_memory_scope ON shared_memory(scope_type, scope_id, status);
CREATE INDEX IF NOT EXISTS idx_route_log_trace ON route_log(trace_id);
CREATE INDEX IF NOT EXISTS idx_route_log_msg ON route_log(msg_id);
CREATE INDEX IF NOT EXISTS idx_task_envelope_trace ON task_envelope(trace_id);

-- Stage 2: task_agent_session association.  Each relay call records the
-- (task_id, agent, relay_session_key, turn) so E2E can verify that the same
-- task+agent reuses one session across turns while different tasks get
-- independent sessions (constraint #2).
CREATE TABLE IF NOT EXISTS task_agent_sessions (
    task_id             TEXT NOT NULL,
    agent_id            TEXT NOT NULL,          -- claude | codex
    relay_session_key   TEXT NOT NULL,          -- relay:hermes-task_xxx:telegram:chatID
    turn                INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    PRIMARY KEY (task_id, agent_id, turn)
);
CREATE INDEX IF NOT EXISTS idx_task_agent_sessions_task ON task_agent_sessions(task_id);
CREATE INDEX IF NOT EXISTS idx_task_agent_sessions_agent ON task_agent_sessions(agent_id, task_id);

-- Stage 2.5: per (chat, agent) conversation epoch for soft session isolation.
-- Stable within an epoch -> relay session reused for natural follow-ups;
-- /manew bumps the epoch -> next relay opens a fresh Claude/Codex session.
CREATE TABLE IF NOT EXISTS relay_conv_epoch (
    chat_id      TEXT NOT NULL,
    agent_id     TEXT NOT NULL,
    epoch        INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (chat_id, agent_id)
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apply_wal(conn: sqlite3.Connection, db_label: str = "multiagent.db") -> None:
    """Enable WAL with fallback to DELETE (mirrors hermes_state.apply_wal_with_fallback)."""
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        logger.warning("%s: WAL unavailable, falling back to DELETE journal", db_label)
        conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")


class MultiAgentStore:
    """Cross-process shared store.  One instance per process is fine; all
    writes go through ``_write`` which holds a lock + BEGIN IMMEDIATE + retry.
    """

    _WRITE_MAX_RETRIES = 6
    _BASE_BACKOFF = 0.05

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=5.0,  # longer than state.db: cross-process contention
            isolation_level=None,  # we manage txns ourselves
        )
        self._conn.row_factory = sqlite3.Row
        _apply_wal(self._conn)
        self._conn.executescript(_SCHEMA_SQL)
        self._migrate_task_envelope()
        logger.info("multiagent store ready at %s", self.db_path)

    def _migrate_task_envelope(self) -> None:
        """Stage 2: add orchestration columns to task_envelope (idempotent).
        ALTER TABLE ADD COLUMN has no IF NOT EXISTS in SQLite, so we probe the
        existing columns first and only add the missing ones."""
        try:
            existing = {row[1] for row in self._conn.execute("PRAGMA table_info(task_envelope)").fetchall()}
        except Exception:
            logger.exception("multiagent: failed to introspect task_envelope")
            return
        additions = {
            # DIRECT|DELEGATE|RESEARCH|DISCUSSION|EXECUTION|REVIEW|PAUSED|DONE
            "mode": "TEXT",
            "review_rework_count": "INTEGER NOT NULL DEFAULT 0",
            "user_intervention": "INTEGER NOT NULL DEFAULT 0",
            # current speaker agent: claude|codex|hermes
            "current_speaker": "TEXT",
            # Magentic-One decay stall counter
            "n_stalls": "INTEGER NOT NULL DEFAULT 0",
            # A2A refinement: derived sub-task links to its parent task
            "parent_task_id": "TEXT",
            "updated_at": "TEXT",
        }
        for col, typedef in additions.items():
            if col not in existing:
                try:
                    self._conn.execute(f"ALTER TABLE task_envelope ADD COLUMN {col} {typedef}")
                    logger.info("multiagent: migrated task_envelope + column %s", col)
                except sqlite3.OperationalError:
                    # Another process raced and added it first - fine.
                    pass

    # ------------------------------------------------------------------
    # low-level write helper (lock + BEGIN IMMEDIATE + retry+backoff)
    # ------------------------------------------------------------------
    def _write(self, fn):
        last_err: Optional[Exception] = None
        for attempt in range(self._WRITE_MAX_RETRIES):
            try:
                with self._lock:
                    self._conn.execute("BEGIN IMMEDIATE")
                    try:
                        result = fn(self._conn)
                        self._conn.commit()
                    except BaseException:
                        try:
                            self._conn.rollback()
                        except Exception:
                            pass
                        raise
                return result
            except sqlite3.OperationalError as exc:
                err = str(exc).lower()
                if "locked" in err or "busy" in err:
                    last_err = exc
                    # jittered exponential backoff
                    time.sleep(self._BASE_BACKOFF * (2 ** attempt) * (0.5 + 0.5 * (attempt % 2)))
                    continue
                raise
        raise last_err  # type: ignore[misc]

    def _read(self, fn):
        with self._lock:
            return fn(self._conn)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # idempotency
    # ------------------------------------------------------------------
    def check_and_mark_idempotent(self, key: str, action: str = "process") -> bool:
        """Return True if *key* was NOT seen before (i.e. this call is the
        first, and the caller should proceed).  False => duplicate, skip."""
        def _fn(c):
            cur = c.execute(
                "INSERT OR IGNORE INTO idempotency(idempotency_key, processed_at, action) VALUES(?,?,?)",
                (key, _now_iso(), action),
            )
            return cur.rowcount > 0
        return self._write(_fn)

    # ------------------------------------------------------------------
    # transcript
    # ------------------------------------------------------------------
    def record_transcript(self, entry: Dict[str, Any]) -> None:
        """Insert or replace a transcript row.  ``entry`` keys map to columns."""
        cols = [
            "msg_id", "platform", "chat_id", "thread_id", "sender_type",
            "sender_id", "sender_name", "agent_id", "text", "reply_to_msg_id",
            "task_id", "trace_id", "trigger_type", "route_reason",
            "observed", "has_images", "has_files", "has_audio", "ts",
        ]
        row = {k: entry.get(k) for k in cols}
        # setdefault won't overwrite an explicit None from entry.get(); use
        # explicit None checks so NOT NULL columns always get a value.
        if not row.get("ts"):
            row["ts"] = _now_iso()
        if row.get("observed") is None:
            row["observed"] = 0
        if row.get("has_images") is None:
            row["has_images"] = 0
        if row.get("has_files") is None:
            row["has_files"] = 0
        if row.get("has_audio") is None:
            row["has_audio"] = 0
        placeholders = ",".join("?" for _ in cols)
        sql = (
            f"INSERT OR REPLACE INTO transcript({','.join(cols)}) VALUES({placeholders})"
        )

        def _fn(c):
            c.execute(sql, [row[k] for k in cols])
        try:
            self._write(_fn)
        except Exception:
            logger.exception("multiagent: failed to record transcript msg_id=%s", row.get("msg_id"))

    def get_transcript_entry(self, chat_id: str, msg_id: str) -> Optional[Dict[str, Any]]:
        def _fn(c):
            cur = c.execute(
                "SELECT * FROM transcript WHERE chat_id=? AND msg_id=?",
                (chat_id, msg_id),
            )
            r = cur.fetchone()
            return dict(r) if r else None
        return self._read(_fn)

    def get_reply_target(self, chat_id: str, reply_to_msg_id: str) -> Optional[Dict[str, Any]]:
        """Look up the message being replied to, for cross-agent reference context.
        Returns the transcript entry (agent_id + text) or None."""
        return self.get_transcript_entry(chat_id, reply_to_msg_id)

    def get_recent_transcript(self, chat_id: str, limit: int = 8
                              ) -> List[Dict[str, Any]]:
        """Return the most recent transcript rows for a chat (newest last), for
        the planner's recent-context window.  Lightweight: no DAG, no resolver -
        just the last N rows so the LLM sees the immediately preceding talk."""
        def _fn(c):
            rows = c.execute(
                "SELECT agent_id, sender_type, text, ts FROM transcript "
                "WHERE chat_id=? ORDER BY ts DESC LIMIT ?",
                (str(chat_id), int(limit)),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]
        return self._read(_fn)

    # ------------------------------------------------------------------
    # msgid -> agent map (audit / Studio / long-term tracking)
    # ------------------------------------------------------------------
    def record_msgid_agent(self, chat_id: str, msg_id: str, agent_id: str,
                           text_preview: str = "") -> None:
        def _fn(c):
            c.execute(
                "INSERT OR REPLACE INTO msgid_agent_map(chat_id,msg_id,agent_id,text_preview,ts) VALUES(?,?,?,?,?)",
                (chat_id, msg_id, agent_id, (text_preview or "")[:200], _now_iso()),
            )
        try:
            self._write(_fn)
        except Exception:
            logger.exception("multiagent: failed to record msgid_agent %s/%s", chat_id, msg_id)

    def get_agent_for_msgid(self, chat_id: str, msg_id: str) -> Optional[str]:
        def _fn(c):
            cur = c.execute(
                "SELECT agent_id FROM msgid_agent_map WHERE chat_id=? AND msg_id=?",
                (chat_id, msg_id),
            )
            r = cur.fetchone()
            return r[0] if r else None
        return self._read(_fn)

    # ------------------------------------------------------------------
    # route log + task envelope
    # ------------------------------------------------------------------
    def record_route(self, trace_id: str, msg_id: str, target_agent: str,
                     trigger_type: str, route_reason: str,
                     wrote_session: bool, wrote_shared: bool) -> None:
        def _fn(c):
            c.execute(
                "INSERT INTO route_log(trace_id,msg_id,target_agent,trigger_type,route_reason,wrote_session,wrote_shared,ts) VALUES(?,?,?,?,?,?,?,?)",
                (trace_id, msg_id, target_agent, trigger_type, route_reason,
                 int(wrote_session), int(wrote_shared), _now_iso()),
            )
        try:
            self._write(_fn)
        except Exception:
            logger.exception("multiagent: failed to record route log trace=%s", trace_id)

    def record_task_envelope(self, env: Dict[str, Any]) -> None:
        cols = [
            "task_id", "context_id", "turn_id", "trace_id", "source",
            "target_agents", "trigger_type", "reply_to_msg_id",
            "reference_msg_ids", "reference_task_ids", "memory_policy",
            "status", "idempotency_key", "hop_count", "max_hops", "ts",
        ]
        row = {k: env.get(k) for k in cols}
        row.setdefault("task_id", uuid.uuid4().hex[:16])
        row.setdefault("trace_id", row["task_id"])
        row.setdefault("status", "pending")
        row.setdefault("hop_count", 0)
        row.setdefault("max_hops", 0)
        # Explicit None checks for NOT NULL columns: env.get returns None when
        # the key is absent, and dict.setdefault does NOT overwrite an existing
        # None value, so a missing "ts" would violate the NOT NULL constraint.
        if not row.get("ts"):
            row["ts"] = _now_iso()
        # JSON-encode list/dict fields
        for k in ("target_agents", "reference_msg_ids", "reference_task_ids", "memory_policy"):
            v = row[k]
            if v is not None and not isinstance(v, str):
                row[k] = json.dumps(v, ensure_ascii=False)
        placeholders = ",".join("?" for _ in cols)
        sql = f"INSERT OR REPLACE INTO task_envelope({','.join(cols)}) VALUES({placeholders})"

        def _fn(c):
            c.execute(sql, [row[k] for k in cols])
        try:
            self._write(_fn)
        except Exception:
            logger.exception("multiagent: failed to record task envelope %s", row.get("task_id"))

    # ------------------------------------------------------------------
    # Stage 2: orchestration task lifecycle (A2A-flavoured)
    # ------------------------------------------------------------------
    def create_task(self, *, chat_id: str, source: str, trigger_type: str,
                    target_agents: List[str], mode: str = "DELEGATE",
                    user_request: str = "", reply_to_msg_id: str = "",
                    parent_task_id: Optional[str] = None) -> str:
        """Create an orchestrated task.  Returns the new task_id.

        ``mode`` is the orchestration mode (DIRECT/DELEGATE/RESEARCH/DISCUSSION/
        EXECUTION/REVIEW/PAUSED/DONE).  The task_id is hex (no colon) so it is
        safe to embed in the cc-connect relay fromProject ``hermes-task_{id}``.
        """
        task_id = uuid.uuid4().hex[:12]
        now = _now_iso()
        # record_task_envelope writes the base 16 columns; the Stage 2
        # orchestration columns (mode/parent_task_id/...) are added by
        # _migrate_task_envelope but NOT in record_task_envelope's fixed cols
        # list, so write them via update_task right after.
        env = {
            "task_id": task_id,
            "trace_id": task_id,
            "source": source,
            "target_agents": target_agents,
            "trigger_type": trigger_type,
            "reply_to_msg_id": reply_to_msg_id,
            "reference_msg_ids": [],
            "reference_task_ids": [parent_task_id] if parent_task_id else [],
            "memory_policy": {"user_request": user_request[:2000]} if user_request else {},
            "status": "working",
            "idempotency_key": f"task:{chat_id}:{task_id}",
            "hop_count": 0,
            "max_hops": 0,
            "ts": now,
        }
        self.record_task_envelope(env)
        self.update_task(
            task_id, mode=mode, review_rework_count=0, user_intervention=0,
            current_speaker=None, n_stalls=0, parent_task_id=parent_task_id,
        )
        logger.info("multiagent: task created id=%s mode=%s targets=%s", task_id, mode, target_agents)
        return task_id

    def update_task(self, task_id: str, **fields: Any) -> None:
        """Update orchestration fields on a task (status/mode/current_speaker/
        n_stalls/review_rework_count/user_intervention/hop_count/...)."""
        if not fields:
            return
        fields = dict(fields)
        fields["updated_at"] = _now_iso()
        # JSON-encode list/dict values
        for k, v in list(fields.items()):
            if v is not None and not isinstance(v, (str, int, float)):
                fields[k] = json.dumps(v, ensure_ascii=False)
        set_clause = ", ".join(f"{k}=?" for k in fields)
        sql = f"UPDATE task_envelope SET {set_clause} WHERE task_id=?"

        def _fn(c):
            c.execute(sql, [*fields.values(), task_id])
        try:
            self._write(_fn)
        except Exception:
            logger.exception("multiagent: failed to update task %s", task_id)

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        def _fn(c):
            r = c.execute("SELECT * FROM task_envelope WHERE task_id=?", (task_id,)).fetchone()
            return dict(r) if r else None
        return self._read(_fn)

    def get_active_tasks(self, chat_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return non-terminal tasks (not DONE/CANCELED/failed), optionally
        filtered to a chat.  Used for multi-task clarification (constraint #5)."""
        def _fn(c):
            sql = ("SELECT * FROM task_envelope "
                   "WHERE status NOT IN ('DONE','canceled','failed') "
                   "ORDER BY updated_at DESC")
            rows = c.execute(sql).fetchall()
            out = [dict(r) for r in rows]
            if chat_id:
                # task_envelope has no chat_id column; filter via the
                # idempotency_key which embeds chat_id ("task:{chat}:{id}").
                out = [r for r in out if f":{chat_id}:" in (r.get("idempotency_key") or "")]
            return out
        return self._read(_fn)

    def get_task_for_msg(self, chat_id: str, msg_id: str) -> Optional[str]:
        """Resolve which task a replied-to message belongs to, by looking up
        the transcript row for (chat_id, msg_id) and reading its task_id.
        Used for user mid-task Reply routing (constraint #5)."""
        def _fn(c):
            r = c.execute(
                "SELECT task_id FROM transcript WHERE chat_id=? AND msg_id=?",
                (chat_id, msg_id),
            ).fetchone()
            return r[0] if r and r[0] else None
        return self._read(_fn)

    def record_task_agent_session(self, task_id: str, agent_id: str,
                                  relay_session_key: str, turn: int) -> None:
        """Record that a relay call used this (task, agent, session_key, turn).
        Enables E2E verification of session reuse vs isolation (constraint #2)."""
        def _fn(c):
            c.execute(
                "INSERT OR REPLACE INTO task_agent_sessions"
                "(task_id,agent_id,relay_session_key,turn,created_at) VALUES(?,?,?,?,?)",
                (task_id, agent_id, relay_session_key, turn, _now_iso()),
            )
        try:
            self._write(_fn)
        except Exception:
            logger.exception("multiagent: failed to record task_agent_session %s/%s", task_id, agent_id)

    # ------------------------------------------------------------------
    # Stage 2.5: soft session isolation (Natural continuity over perfect
    # isolation).  A relay conversation key is stable per (chat, agent, epoch)
    # so natural follow-ups reuse the same Claude/Codex conversation; only an
    # explicit /manew bumps the epoch.  task_id still tracks each delegation
    # for audit, but no longer forces a brand-new agent session.
    # ------------------------------------------------------------------

    def relay_conversation_epoch(self, chat_id: str, agent_id: str) -> int:
        """Return the current conversation epoch for (chat, agent).

        0 = first epoch.  /manew increments it so the next relay opens a fresh
        cc-connect relay session (relay:hermes-conv:{chat}:{agent}:{epoch}).
        """
        def _fn(c):
            r = c.execute(
                "SELECT epoch FROM relay_conv_epoch WHERE chat_id=? AND agent_id=?",
                (str(chat_id), str(agent_id)),
            ).fetchone()
            return int(r[0]) if r else 0
        return self._read(_fn)

    def bump_relay_conversation_epoch(self, chat_id: str, agent_id: str) -> int:
        """Increment (creating if needed) the epoch for (chat, agent).  Returns
        the new epoch value.  Used by /manew to force a fresh conversation."""
        now = _now_iso()
        def _fn(c):
            c.execute(
                "INSERT INTO relay_conv_epoch(chat_id, agent_id, epoch, updated_at) "
                "VALUES(?, ?, 1, ?) "
                "ON CONFLICT(chat_id, agent_id) DO UPDATE SET "
                "  epoch=epoch+1, updated_at=excluded.updated_at",
                (str(chat_id), str(agent_id), now),
            )
            r = c.execute(
                "SELECT epoch FROM relay_conv_epoch WHERE chat_id=? AND agent_id=?",
                (str(chat_id), str(agent_id)),
            ).fetchone()
            return int(r[0]) if r else 1
        try:
            return self._write(_fn)
        except Exception:
            logger.exception("multiagent: failed to bump relay epoch %s/%s", chat_id, agent_id)
            return self.relay_conversation_epoch(chat_id, agent_id)

    def get_task_agent_sessions(self, task_id: str) -> List[Dict[str, Any]]:
        def _fn(c):
            return [dict(r) for r in c.execute(
                "SELECT * FROM task_agent_sessions WHERE task_id=? ORDER BY turn", (task_id,)
            ).fetchall()]
        return self._read(_fn)

    def get_route_log(self, msg_id: Optional[str] = None,
                      trace_id: Optional[str] = None,
                      limit: int = 20) -> List[Dict[str, Any]]:
        def _fn(c):
            if msg_id:
                cur = c.execute(
                    "SELECT * FROM route_log WHERE msg_id=? ORDER BY ts DESC LIMIT ?",
                    (msg_id, limit),
                )
            elif trace_id:
                cur = c.execute(
                    "SELECT * FROM route_log WHERE trace_id=? ORDER BY ts DESC LIMIT ?",
                    (trace_id, limit),
                )
            else:
                cur = c.execute(
                    "SELECT * FROM route_log ORDER BY ts DESC LIMIT ?", (limit,)
                )
            return [dict(r) for r in cur.fetchall()]
        return self._read(_fn)

    # ------------------------------------------------------------------
    # shared memory
    # ------------------------------------------------------------------
    def add_shared_memory(self, scope_type: str, scope_id: str, content: str,
                          created_by: str, source_msg_id: Optional[str] = None,
                          supersedes_id: Optional[str] = None) -> str:
        """Write a shared-memory fact.  If *supersedes_id* is given, the old
        fact is marked ``superseded`` and linked.  Returns the new memory_id."""
        memory_id = uuid.uuid4().hex[:16]
        now = _now_iso()

        def _fn(c):
            c.execute(
                "INSERT INTO shared_memory(memory_id,scope_type,scope_id,content,source_msg_id,created_by,created_at,status,supersedes_id,version) VALUES(?,?,?,?,?,?,?,?,?,1)",
                (memory_id, scope_type, scope_id, content, source_msg_id,
                 created_by, now, "active", supersedes_id),
            )
            if supersedes_id:
                c.execute(
                    "UPDATE shared_memory SET status='superseded', replaced_by_id=? WHERE memory_id=?",
                    (memory_id, supersedes_id),
                )
        self._write(_fn)
        logger.info("multiagent: shared memory added id=%s scope=%s/%s", memory_id, scope_type, scope_id)
        return memory_id

    def list_shared_memory(self, scope_type: Optional[str] = None,
                           scope_id: Optional[str] = None,
                           include_deleted: bool = False) -> List[Dict[str, Any]]:
        def _fn(c):
            sql = "SELECT * FROM shared_memory WHERE 1=1"
            args: List[Any] = []
            if scope_type:
                sql += " AND scope_type=?"
                args.append(scope_type)
            if scope_id:
                sql += " AND scope_id=?"
                args.append(scope_id)
            if not include_deleted:
                # Active only: exclude both 'deleted' and 'superseded'.
                sql += " AND status='active'"
            sql += " ORDER BY created_at DESC"
            cur = c.execute(sql, args)
            return [dict(r) for r in cur.fetchall()]
        return self._read(_fn)

    def forget_shared_memory(self, memory_id: str) -> bool:
        """Logically delete (status='deleted'), not physical, for audit."""
        def _fn(c):
            cur = c.execute(
                "UPDATE shared_memory SET status='deleted' WHERE memory_id=? AND status!='deleted'",
                (memory_id,),
            )
            return cur.rowcount > 0
        return self._write(_fn)

    def get_active_shared_memory_text(self, scope_type: str, scope_id: str) -> str:
        """Return a formatted block of active shared facts for a scope, for
        injection into the Hermes agent context (read-only)."""
        rows = self.list_shared_memory(scope_type=scope_type, scope_id=scope_id)
        if not rows:
            return ""
        lines = ["[Shared Memory — confirmed public facts for this scope]"]
        for r in rows:
            lines.append(f"- ({r['memory_id']}) {r['content']}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # maintenance
    # ------------------------------------------------------------------
    def checkpoint(self) -> None:
        try:
            self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_store: Optional[MultiAgentStore] = None
_store_lock = threading.Lock()


def get_store(db_path: Optional[Path] = None) -> MultiAgentStore:
    """Process-wide singleton.  ``db_path`` only honored on first call."""
    global _store
    if _store is not None:
        return _store
    with _store_lock:
        if _store is not None:
            return _store
        if db_path is None:
            # Resolve HERMES_HOME the same way hermes_constants does.
            home = os.environ.get("HERMES_HOME", "").strip()
            if home:
                base = Path(home)
            else:
                base = Path.home() / ".hermes"
            db_path = base / "multiagent.db"
        _store = MultiAgentStore(db_path)
        return _store

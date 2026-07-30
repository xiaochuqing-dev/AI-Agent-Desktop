"""Unit tests for the shared MultiAgentStore (SQLite, cross-process)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

from plugins.multiagent.store import MultiAgentStore


@pytest.fixture
def store(tmp_path) -> MultiAgentStore:
    return MultiAgentStore(tmp_path / "test-multiagent.db")


# M. Idempotency: same (chat_id, msg_id) processed twice -> only once
def test_idempotency_dedup(store):
    key = "-100:42"
    assert store.check_and_mark_idempotent(key) is True   # first -> proceed
    assert store.check_and_mark_idempotent(key) is False  # dup -> skip


def test_idempotency_different_keys(store):
    assert store.check_and_mark_idempotent("-100:42") is True
    assert store.check_and_mark_idempotent("-100:43") is True
    assert store.check_and_mark_idempotent("-100:42") is False


# Transcript record + read
def test_transcript_record_and_read(store):
    store.record_transcript({
        "msg_id": "100", "platform": "telegram", "chat_id": "-100",
        "sender_type": "human", "agent_id": "human", "text": "hello",
    })
    entry = store.get_transcript_entry("-100", "100")
    assert entry is not None
    assert entry["text"] == "hello"
    assert entry["agent_id"] == "human"


# Cross-agent reference lookup via transcript
def test_transcript_reply_lookup(store):
    store.record_transcript({
        "msg_id": "555", "platform": "telegram", "chat_id": "-100",
        "sender_type": "bot", "agent_id": "claude", "text": "方案A",
    })
    target = store.get_reply_target("-100", "555")
    assert target is not None
    assert target["agent_id"] == "claude"
    assert target["text"] == "方案A"


# msgid -> agent map
def test_msgid_agent_map(store):
    store.record_msgid_agent("-100", "555", "claude", "方案A")
    assert store.get_agent_for_msgid("-100", "555") == "claude"
    assert store.get_agent_for_msgid("-100", "999") is None


# H. Shared Memory write + read
def test_shared_memory_write_read(store):
    mid = store.add_shared_memory("group", "-100", "代号是456", "REPLACE_WITH_YOUR_USER_ID")
    rows = store.list_shared_memory(scope_type="group", scope_id="-100")
    assert len(rows) == 1
    assert rows[0]["memory_id"] == mid
    assert rows[0]["content"] == "代号是456"
    assert rows[0]["status"] == "active"
    assert rows[0]["source_msg_id"] is None


# I. Reply + /mashare -> source_msg_id recorded
def test_shared_memory_with_source(store):
    mid = store.add_shared_memory("group", "-100", "被回复内容", "user1",
                                  source_msg_id="555")
    rows = store.list_shared_memory(scope_type="group", scope_id="-100")
    assert rows[0]["source_msg_id"] == "555"


# /forget -> logical delete, not physical
def test_shared_memory_forget_logical(store):
    mid = store.add_shared_memory("group", "-100", "temp fact", "user1")
    assert store.forget_shared_memory(mid) is True
    # Active list should be empty
    active = store.list_shared_memory(scope_type="group", scope_id="-100")
    assert len(active) == 0
    # But including deleted shows it (audit)
    all_rows = store.list_shared_memory(scope_type="group", scope_id="-100",
                                        include_deleted=True)
    assert len(all_rows) == 1
    assert all_rows[0]["status"] == "deleted"


# Conflict: new fact supersedes old
def test_shared_memory_supersede(store):
    old = store.add_shared_memory("group", "-100", "用MySQL", "user1")
    new = store.add_shared_memory("group", "-100", "改用PostgreSQL", "user1",
                                  supersedes_id=old)
    rows = store.list_shared_memory(scope_type="group", scope_id="-100")
    assert len(rows) == 1  # old is superseded -> not in active list
    assert rows[0]["memory_id"] == new
    assert rows[0]["content"] == "改用PostgreSQL"
    # Old is marked superseded
    all_rows = store.list_shared_memory(scope_type="group", scope_id="-100",
                                        include_deleted=True)
    old_row = [r for r in all_rows if r["memory_id"] == old][0]
    assert old_row["status"] == "superseded"
    assert old_row["replaced_by_id"] == new


# get_active_shared_memory_text for context injection
def test_shared_memory_text_injection(store):
    store.add_shared_memory("group", "-100", "事实1", "user1")
    store.add_shared_memory("group", "-100", "事实2", "user1")
    text = store.get_active_shared_memory_text("group", "-100")
    assert "Shared Memory" in text
    assert "事实1" in text
    assert "事实2" in text


# Route log
def test_route_log(store):
    store.record_route("trace1", "100", "hermes", "mention", "explicit @", True, False)
    logs = store.get_route_log(msg_id="100")
    assert len(logs) == 1
    assert logs[0]["target_agent"] == "hermes"
    assert logs[0]["wrote_session"] == 1
    assert logs[0]["wrote_shared"] == 0


# O. Restart persistence: data survives store close+reopen
def test_persistence_across_reopen(tmp_path):
    s1 = MultiAgentStore(tmp_path / "persist.db")
    s1.add_shared_memory("group", "-100", "persistent fact", "user1")
    s1.record_transcript({"msg_id": "1", "platform": "telegram",
                          "chat_id": "-100", "sender_type": "human",
                          "agent_id": "human", "text": "hi"})
    s1.close()
    s2 = MultiAgentStore(tmp_path / "persist.db")
    rows = s2.list_shared_memory(scope_type="group", scope_id="-100")
    assert len(rows) == 1
    assert rows[0]["content"] == "persistent fact"
    entry = s2.get_transcript_entry("-100", "1")
    assert entry is not None
    assert entry["text"] == "hi"
    s2.close()


# Scope isolation: group vs topic
def test_scope_isolation(store):
    store.add_shared_memory("group", "-100", "group fact", "u1")
    store.add_shared_memory("topic", "100", "topic fact", "u1")
    group_rows = store.list_shared_memory(scope_type="group", scope_id="-100")
    topic_rows = store.list_shared_memory(scope_type="topic", scope_id="100")
    assert len(group_rows) == 1
    assert group_rows[0]["content"] == "group fact"
    assert len(topic_rows) == 1
    assert topic_rows[0]["content"] == "topic fact"


# ===========================================================================
# Stage 2: orchestration task lifecycle
# ===========================================================================

def test_task_envelope_migration_adds_columns(store):
    """The Stage 2 migration must add the orchestration columns idempotently."""
    import sqlite3
    cols = {row[1] for row in store._conn.execute("PRAGMA table_info(task_envelope)").fetchall()}
    for c in ("mode", "review_rework_count", "user_intervention", "current_speaker",
              "n_stalls", "parent_task_id", "updated_at"):
        assert c in cols, f"missing migrated column: {c}"


def test_create_task_returns_hex_id(store):
    tid = store.create_task(
        chat_id="-100", source="u1", trigger_type="orchestrator",
        target_agents=["claude"], mode="DELEGATE", user_request="分析X",
    )
    assert len(tid) == 12
    assert ":" not in tid  # safe for relay fromProject "hermes-task_{tid}"
    t = store.get_task(tid)
    assert t is not None
    assert t["mode"] == "DELEGATE"
    assert t["status"] == "working"
    assert t["review_rework_count"] == 0


def test_update_task_fields(store):
    tid = store.create_task(chat_id="-100", source="u1", trigger_type="orchestrator",
                            target_agents=["claude"], mode="DISCUSSION")
    store.update_task(tid, status="PAUSED", mode="DISCUSSION", current_speaker="claude",
                      n_stalls=2, review_rework_count=1)
    t = store.get_task(tid)
    assert t["status"] == "PAUSED"
    assert t["current_speaker"] == "claude"
    assert t["n_stalls"] == 2
    assert t["review_rework_count"] == 1
    assert t["updated_at"] is not None


def test_review_rework_same_task_id(store):
    """Constraint #5: rework keeps the same task_id, only increments counter."""
    tid = store.create_task(chat_id="-100", source="u1", trigger_type="orchestrator",
                            target_agents=["claude"], mode="EXECUTION")
    # First rework round
    store.update_task(tid, review_rework_count=1, status="working", mode="REVIEW")
    # Second rework round
    store.update_task(tid, review_rework_count=2, status="working", mode="REVIEW")
    t = store.get_task(tid)
    assert t["review_rework_count"] == 2
    assert t["task_id"] == tid  # same task, no new id


def test_parent_task_id_only_for_derived(store):
    """parent_task_id is only set when explicitly deriving a new sub-task."""
    parent = store.create_task(chat_id="-100", source="u1", trigger_type="orchestrator",
                               target_agents=["claude"], mode="DELEGATE")
    child = store.create_task(chat_id="-100", source="u1", trigger_type="orchestrator",
                              target_agents=["codex"], mode="DELEGATE",
                              parent_task_id=parent)
    assert store.get_task(child)["parent_task_id"] == parent
    assert store.get_task(parent)["parent_task_id"] is None


def test_get_active_tasks_filters_terminal(store):
    t1 = store.create_task(chat_id="-100", source="u1", trigger_type="orchestrator",
                           target_agents=["claude"], mode="DELEGATE")
    t2 = store.create_task(chat_id="-100", source="u1", trigger_type="orchestrator",
                           target_agents=["codex"], mode="DELEGATE")
    store.update_task(t1, status="DONE")
    active = store.get_active_tasks()
    ids = [t["task_id"] for t in active]
    assert t2 in ids
    assert t1 not in ids


def test_get_active_tasks_filter_by_chat(store):
    t1 = store.create_task(chat_id="-100", source="u1", trigger_type="orchestrator",
                           target_agents=["claude"], mode="DELEGATE")
    t2 = store.create_task(chat_id="-200", source="u1", trigger_type="orchestrator",
                           target_agents=["codex"], mode="DELEGATE")
    active_100 = store.get_active_tasks(chat_id="-100")
    assert len(active_100) == 1
    assert active_100[0]["task_id"] == t1


def test_task_agent_session_record_and_isolation(store):
    """Stage 2.5 (soft isolation): the conversation key is stable per
    (chat, agent, epoch) and reused across task_ids within an epoch; a new
    epoch (via /manew) yields a different key.  record_task_agent_session just
    records whatever key is passed; the relay_client derives the key."""
    # Epoch 0: two different task_ids, same agent -> SAME conversation key
    # (natural follow-up continuity).
    tid_a = store.create_task(chat_id="-100", source="u1", trigger_type="orchestrator",
                              target_agents=["claude"], mode="DISCUSSION")
    tid_b = store.create_task(chat_id="-100", source="u1", trigger_type="orchestrator",
                              target_agents=["claude"], mode="DISCUSSION")
    key_e0 = "relay:hermes-conv_-100_claude_0:telegram:-100"
    store.record_task_agent_session(tid_a, "claude", key_e0, turn=0)
    store.record_task_agent_session(tid_b, "claude", key_e0, turn=0)

    sess_a = store.get_task_agent_sessions(tid_a)
    sess_b = store.get_task_agent_sessions(tid_b)
    assert len(sess_a) == 1
    assert len(sess_b) == 1
    # Both tasks recorded the SAME key (continuity), different task_ids (audit).
    assert sess_a[0]["relay_session_key"] == key_e0
    assert sess_b[0]["relay_session_key"] == key_e0
    assert sess_a[0]["task_id"] != sess_b[0]["task_id"]


def test_relay_conversation_epoch_bump(store):
    """Stage 2.5: /manew bumps the epoch so the next relay opens a fresh
    conversation; default epoch is 0."""
    assert store.relay_conversation_epoch("-100", "claude") == 0
    e1 = store.bump_relay_conversation_epoch("-100", "claude")
    assert e1 == 1
    assert store.relay_conversation_epoch("-100", "claude") == 1
    e2 = store.bump_relay_conversation_epoch("-100", "claude")
    assert e2 == 2
    # Different agent has its own epoch.
    assert store.relay_conversation_epoch("-100", "codex") == 0


def test_get_task_for_msg_via_transcript(store):
    """User Reply routing: resolve task_id from transcript's task_id column."""
    store.record_transcript({
        "msg_id": "500", "platform": "telegram", "chat_id": "-100",
        "sender_type": "bot", "agent_id": "claude", "text": "claude reply",
        "task_id": "taskabc123", "trigger_type": "relay",
    })
    assert store.get_task_for_msg("-100", "500") == "taskabc123"
    assert store.get_task_for_msg("-100", "999") is None  # unknown msg

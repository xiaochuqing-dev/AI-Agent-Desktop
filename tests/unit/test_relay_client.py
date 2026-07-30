"""Unit tests for the Stage 2 relay client (hop guard + session-key isolation).

These do NOT call a real cc-connect; the subprocess path is exercised via a
fake binary that echoes a canned reply.  The guard logic (ping-pong, repeat,
max-hops, session-key derivation) is the focus.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

from plugins.multiagent.relay_client import RelayClient, HopGuard, _is_ping_pong, _hash_text


# ---------------------------------------------------------------------------
# Pure-function guard logic
# ---------------------------------------------------------------------------

def test_ping_pong_detection():
    assert _is_ping_pong([]) is False
    assert _is_ping_pong(["a", "b"]) is False
    assert _is_ping_pong(["a", "b", "a"]) is False
    assert _is_ping_pong(["a", "b", "a", "b"]) is True       # 2 full cycles
    assert _is_ping_pong(["a", "b", "a", "b", "a"]) is True   # tail still ping-pong
    assert _is_ping_pong(["a", "b", "c", "a"]) is False       # third voice breaks it
    assert _is_ping_pong(["a", "a", "a", "a"]) is False       # same agent != ping-pong


def test_hash_text_normalises():
    assert _hash_text("Hello") == _hash_text("hello")
    assert _hash_text(" Hello ") == _hash_text("hello")
    assert _hash_text("a") != _hash_text("b")


def test_hop_guard_max_hops():
    g = HopGuard(hop_count=5)
    assert g.would_exceed_max_hops(5) is True
    assert g.would_exceed_max_hops(6) is False


# ---------------------------------------------------------------------------
# RelayClient conversation-key continuity (Stage 2.5: soft isolation)
# ---------------------------------------------------------------------------

def _epoch_store(epoch: int = 0):
    """A fake store whose relay_conversation_epoch returns a fixed epoch."""
    store = mock.MagicMock()
    store.relay_conversation_epoch.return_value = epoch
    return store


def test_relay_session_key_stable_within_epoch():
    """Same (chat, agent, epoch) reuses one relay session across task_ids:
    natural follow-up continuity (the fix for follow-up amnesia)."""
    store = _epoch_store(epoch=0)
    c_a = RelayClient(store, chat_id="-100", task_id="aaa111222333")
    c_b = RelayClient(store, chat_id="-100", task_id="bbb333444555")
    key_a = c_a.relay_session_key("claude")
    key_b = c_b.relay_session_key("claude")
    # Different task_ids, SAME conversation key -> Claude remembers the code.
    assert key_a == "relay:hermes-conv_-100_claude_0:telegram:-100"
    assert key_b == key_a
    # Stable across calls.
    assert c_a.relay_session_key("claude") == key_a


def test_relay_session_key_isolates_per_agent():
    """Different agent -> different conversation key (Claude != Codex)."""
    store = _epoch_store(epoch=0)
    c = RelayClient(store, chat_id="-100", task_id="aaa111222333")
    assert c.relay_session_key("claude") != c.relay_session_key("codex")
    assert "claude" in c.relay_session_key("claude")
    assert "codex" in c.relay_session_key("codex")


def test_relay_session_key_epoch_bump_forces_new_session():
    """/manew bumps the epoch -> a fresh conversation key (soft isolation when
    the user explicitly asks for a new session)."""
    store = _epoch_store(epoch=0)
    c = RelayClient(store, chat_id="-100", task_id="aaa111222333")
    key_e0 = c.relay_session_key("claude")
    store.relay_conversation_epoch.return_value = 1  # simulate /manew
    key_e1 = c.relay_session_key("claude")
    assert key_e0 != key_e1
    assert "_0:" in key_e0 and "_1:" in key_e1


def test_relay_session_key_no_colon_in_from_project():
    """from_project part must contain no ':' (parseSessionKeyParts safety)."""
    store = _epoch_store(epoch=0)
    c = RelayClient(store, chat_id="-100", task_id="deadbeef1234")
    key = c.relay_session_key("claude")
    # "relay:hermes-conv_-100_claude_0:telegram:-100" -> the segment between
    # the first two ':' is the from_project (no embedded colon).
    parts = key.split(":", 2)
    assert parts[1] == "hermes-conv_-100_claude_0"
    assert ":" not in parts[1]


def test_relay_session_key_no_store_falls_back_to_epoch_0():
    """If the store lookup fails, the client must still derive a key (epoch 0)."""
    c = RelayClient(None, chat_id="-100", task_id="aaa")
    key = c.relay_session_key("claude")
    assert key == "relay:hermes-conv_-100_claude_0:telegram:-100"


# ---------------------------------------------------------------------------
# send() with a fake cc-connect binary
# ---------------------------------------------------------------------------

def _fake_run_factory(reply: str, returncode: int = 0, stderr: str = ""):
    """Build a mock for subprocess.run returning a canned relay reply."""
    fake = mock.MagicMock()
    fake.returncode = returncode
    fake.stdout = reply
    fake.stderr = stderr
    return fake


def test_send_success_records_session_and_returns_reply():
    store = _epoch_store(epoch=0)
    c = RelayClient(store, chat_id="-100", task_id="aaa111222333", cc_bin="/fake/cc")
    with mock.patch("plugins.multiagent.relay_client.subprocess.run",
                    return_value=_fake_run_factory("这是Claude的分析结果")):
        ok, reply = c.send("claude-expert", "claude", "请分析", turn=0)
    assert ok is True
    assert reply == "这是Claude的分析结果"
    # task_agent_session recorded for audit (constraint #2).  The conversation
    # key is stable per (chat, agent, epoch), NOT per task_id.
    store.record_task_agent_session.assert_called_once_with(
        "aaa111222333", "claude", "relay:hermes-conv_-100_claude_0:telegram:-100", 0,
    )
    assert c.guard.hop_count == 1


def test_send_failure_returns_error_no_session_record():
    store = _epoch_store(epoch=0)
    c = RelayClient(store, chat_id="-100", task_id="aaa111222333", cc_bin="/fake/cc")
    with mock.patch("plugins.multiagent.relay_client.subprocess.run",
                    return_value=_fake_run_factory("", returncode=1, stderr="no binding")):
        ok, reply = c.send("codex-expert", "codex", "请分析", turn=0)
    assert ok is False
    assert "no binding" in reply
    store.record_task_agent_session.assert_not_called()


def test_send_updates_repeat_detection():
    store = _epoch_store(epoch=0)
    c = RelayClient(store, chat_id="-100", task_id="aaa111222333", cc_bin="/fake/cc")
    runner = _fake_run_factory("same reply")
    with mock.patch("plugins.multiagent.relay_client.subprocess.run", return_value=runner):
        c.send("claude-expert", "claude", "turn1", turn=0)
        c.send("claude-expert", "claude", "turn2", turn=1)
    assert c.guard.consecutive_repeat == 1  # two identical replies
    # A different reply resets the counter.
    runner.stdout = "different reply"
    with mock.patch("plugins.multiagent.relay_client.subprocess.run", return_value=runner):
        c.send("claude-expert", "claude", "turn3", turn=2)
    assert c.guard.consecutive_repeat == 0


def test_send_tracks_speaker_sequence_and_ping_pong():
    store = _epoch_store(epoch=0)
    c = RelayClient(store, chat_id="-100", task_id="aaa111222333", cc_bin="/fake/cc")
    runner = _fake_run_factory("reply")
    with mock.patch("plugins.multiagent.relay_client.subprocess.run", return_value=runner):
        c.send("claude-expert", "claude", "t0", turn=0)
        assert c.guard.ping_pong_detected is False
        c.send("codex-expert", "codex", "t1", turn=1)
        assert c.guard.ping_pong_detected is False
        c.send("claude-expert", "claude", "t2", turn=2)
        assert c.guard.ping_pong_detected is False
        c.send("codex-expert", "codex", "t3", turn=3)
        # claude->codex->claude->codex = ping-pong flagged (not blocked).
        assert c.guard.ping_pong_detected is True
        assert c.guard.speaker_sequence == ["claude", "codex", "claude", "codex"]


def test_same_agent_can_speak_multiple_times():
    """Constraint correction #2: the guard must NOT block repeated calls to the
    same agent within one task (normal multi-turn discussion allows this)."""
    store = _epoch_store(epoch=0)
    c = RelayClient(store, chat_id="-100", task_id="aaa111222333", cc_bin="/fake/cc")
    runner = _fake_run_factory("reply")
    with mock.patch("plugins.multiagent.relay_client.subprocess.run", return_value=runner):
        for i in range(5):
            ok, _ = c.send("claude-expert", "claude", f"turn{i}", turn=i)
            assert ok is True  # never blocked
    assert c.guard.hop_count == 5
    # All-claude sequence is NOT ping-pong.
    assert c.guard.ping_pong_detected is False


def test_timeout_returns_error_without_raising():
    import subprocess as sp
    store = _epoch_store(epoch=0)
    c = RelayClient(store, chat_id="-100", task_id="aaa111222333", cc_bin="/fake/cc",
                    default_timeout=1)
    with mock.patch("plugins.multiagent.relay_client.subprocess.run",
                    side_effect=sp.TimeoutExpired(cmd=["x"], timeout=1)):
        ok, reply = c.send("claude-expert", "claude", "t", turn=0)
    assert ok is False
    assert "timeout" in reply.lower()

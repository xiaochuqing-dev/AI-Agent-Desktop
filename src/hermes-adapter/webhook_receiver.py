"""Localhost HTTP receiver for cc-connect hook events.

cc-connect fires ``message.received`` and ``message.sent_delivered`` hooks as
HTTP POSTs (type="http").  This receiver accepts them and writes the data into
the shared ``multiagent.db`` Transcript / msgid_agent_map.

Security & reliability (per stage-1.5 constraint 3):
  * Binds **localhost only** (127.0.0.1) - never exposed to the network.
  * Authenticates via ``Authorization: Bearer <secret>`` header.  URL-query
    tokens are NOT accepted (they leak into logs).  Rejects all posts without
    a valid bearer token.
  * Idempotent: dedup by (event, chat_id, msg_id) so a cc-connect hook retry
    never writes a duplicate transcript row.
  * Best-effort: if the DB write fails after 3 internal retries, the event is
    logged and dropped.  cc-connect's hook is fire-and-forget, so the
    *pipeline* is best-effort by nature - the Transcript is marked 🟡 in the
    report.  The store itself (WAL + fsync) is durable.

Lifecycle: started once by the plugin's ``register()`` on first
``pre_gateway_dispatch`` fire, in a daemon thread.  Stops with the gateway
process.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from .config import MultiAgentConfig
from .store import MultiAgentStore

logger = logging.getLogger(__name__)

_server: Optional[ThreadingHTTPServer] = None
_server_lock = threading.Lock()


def _agent_id_from_project(project: str) -> str:
    """Map a cc-connect project name to an agent_id."""
    p = (project or "").lower()
    if "claude" in p:
        return "claude"
    if "codex" in p:
        return "codex"
    if "hermes" in p:
        return "hermes"
    return p or "unknown"


def _parse_session_key(session_key: str) -> Dict[str, str]:
    """Parse cc-connect's session_key ``telegram:{chatID}[:{threadID}]:{userID}``."""
    out: Dict[str, str] = {"chat_id": "", "thread_id": "", "user_id": ""}
    if not session_key:
        return out
    parts = session_key.split(":")
    # parts[0] = platform, then chat_id, optional thread_id, user_id
    if len(parts) >= 2:
        out["chat_id"] = parts[1]
    if len(parts) == 4:
        out["thread_id"] = parts[2]
        out["user_id"] = parts[3]
    elif len(parts) == 3:
        out["user_id"] = parts[2]
    return out


class _HookHandler(BaseHTTPRequestHandler):
    """Handles POST /cc-event from cc-connect hooks."""

    # Suppress default logging (keeps the gateway log clean).
    def log_message(self, fmt, *args):  # noqa: D401
        pass

    def do_POST(self) -> None:  # noqa: N802
        cfg: MultiAgentConfig = self.server.cfg  # type: ignore[attr-defined]
        store: MultiAgentStore = self.server.store  # type: ignore[attr-defined]

        # --- Auth: require Authorization: Bearer <secret> ---
        auth = self.headers.get("Authorization", "")
        expected = f"Bearer {cfg.receiver_secret}"
        if not auth or auth != expected:
            logger.warning("multiagent receiver: rejected unauthenticated POST (auth=%r)", auth[:30])
            self.send_response(401)
            self.end_headers()
            return

        # Read body
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length > 0 else b""
            payload: Dict[str, Any] = json.loads(body) if body else {}
        except Exception:
            logger.exception("multiagent receiver: failed to parse body")
            self.send_response(400)
            self.end_headers()
            return

        event_type = payload.get("event", "")
        project = payload.get("project", "")
        session_key = payload.get("session_key", "")
        content = payload.get("content", "")
        user_id = payload.get("user_id", "")
        user_name = payload.get("user_name", "")
        extra: Dict[str, Any] = payload.get("extra") or {}
        sk = _parse_session_key(session_key)

        # --- Idempotency: dedup by (event, chat_id, msg_id) ---
        msg_id = str(extra.get("message_id") or "")
        chat_id = sk["chat_id"] or str(extra.get("chat_id") or "")
        if msg_id and chat_id:
            idem_key = f"hook:{event_type}:{chat_id}:{msg_id}"
            if not store.check_and_mark_idempotent(idem_key, action=f"hook_{event_type}"):
                # Duplicate - ack so cc-connect doesn't keep retrying.
                self.send_response(200)
                self.end_headers()
                return

        agent_id = _agent_id_from_project(project)

        # Stage 2: observable receive log so the hook/msgid chain can be verified
        # in real Telegram runs (constraint #3).  Logs every inbound hook POST.
        logger.info(
            "multiagent receiver: POST event=%s project=%s agent=%s chat=%s msg=%s",
            event_type, project, agent_id, chat_id, msg_id,
        )

        if event_type == "message.received":
            # Inbound message from a user (or another bot) to this cc-connect bot.
            sender_type = extra.get("sender_type", "human")
            store.record_transcript({
                "msg_id": msg_id,
                "platform": "telegram",
                "chat_id": chat_id,
                "thread_id": str(extra.get("thread_id") or sk["thread_id"] or ""),
                "sender_type": sender_type,
                "sender_id": user_id,
                "sender_name": user_name,
                "agent_id": agent_id if sender_type == "bot" else "human",
                "text": (content or "")[:2000],
                "reply_to_msg_id": str(extra.get("reply_to_message_id") or ""),
                "trigger_type": "mention",  # cc-connect only dispatches when directed at bot
                "route_reason": f"cc-connect {project} inbound",
                "observed": 0,
                "has_images": 1 if extra.get("has_images") else 0,
                "has_files": 1 if extra.get("has_files") else 0,
                "has_audio": 1 if extra.get("has_audio") else 0,
            })

        elif event_type == "message.sent_delivered":
            # Outbound message this cc-connect bot just sent.  Record the
            # delivered message_id -> agent map + transcript.
            sent_msg_id = str(extra.get("message_id") or "")
            sent_chat_id = str(extra.get("chat_id") or chat_id)
            sent_thread = str(extra.get("thread_id") or "")
            if sent_msg_id:
                store.record_msgid_agent(sent_chat_id, sent_msg_id, agent_id, content)
                store.record_transcript({
                    "msg_id": sent_msg_id,
                    "platform": "telegram",
                    "chat_id": sent_chat_id,
                    "thread_id": sent_thread,
                    "sender_type": "bot",
                    "sender_id": "",
                    "sender_name": project,
                    "agent_id": agent_id,
                    "text": (content or "")[:2000],
                    "trigger_type": "reply",
                    "route_reason": f"cc-connect {project} outbound delivered",
                    "observed": 0,
                })
                logger.info(
                    "multiagent receiver: recorded outbound agent=%s chat=%s msg=%s (msgid_agent_map updated)",
                    agent_id, sent_chat_id, sent_msg_id,
                )
            else:
                logger.warning(
                    "multiagent receiver: sent_delivered without message_id (project=%s chat=%s) - "
                    "emitSentDelivered may not have captured the id",
                    project, sent_chat_id,
                )

        elif event_type == "message.sent":
            # Pre-send event (no message_id) - skip; we use sent_delivered.
            pass

        # Acknowledge so cc-connect considers the hook delivered.
        self.send_response(200)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        # Health check (no auth needed for a simple liveness probe).
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_response(404)
        self.end_headers()


def start_receiver(cfg: MultiAgentConfig, store: MultiAgentStore) -> None:
    """Start the localhost HTTP receiver in a daemon thread.  Idempotent."""
    global _server
    with _server_lock:
        if _server is not None:
            return
        server = ThreadingHTTPServer((cfg.receiver_host, cfg.receiver_port), _HookHandler)
        server.cfg = cfg  # type: ignore[attr-defined]
        server.store = store  # type: ignore[attr-defined]
        _server = server
        t = threading.Thread(target=server.serve_forever, name="multiagent-hook-receiver", daemon=True)
        t.start()
        logger.info(
            "multiagent receiver: listening on %s:%d (localhost, bearer-auth)",
            cfg.receiver_host, cfg.receiver_port,
        )


def stop_receiver() -> None:
    """Stop the receiver (mainly for tests)."""
    global _server
    with _server_lock:
        if _server is not None:
            _server.shutdown()
            _server = None

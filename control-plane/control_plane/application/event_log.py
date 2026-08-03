# 事件日志:进程内 journal + SSE 订阅。CloudEvents 1.0 信封,at-least-once。
# epoch 为进程级;重启后新 epoch,旧游标过期返回 410(契约 05 §184)。
# 事件结构符合未来可持久化与可重放的模型;首片用进程内队列即可。
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..domain.models import ResourceRef


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Event:
    # CloudEvents 1.0 兼容信封(本地 SSE 承载)
    id: str
    type: str
    source: str
    subject: str
    time: datetime
    sequence: int
    epoch: str
    resourceversion: str
    correlationid: str
    data: dict[str, Any]
    operationid: str | None = None
    severity: str = "info"

    def to_sse(self) -> str:
        # SSE 记录:id 行 / event 行 / data 行
        envelope = {
            "specversion": "1.0",
            "id": self.id,
            "source": self.source,
            "type": self.type,
            "time": self.time.isoformat(),
            "subject": self.subject,
            "datacontenttype": "application/json",
            "sequence": self.sequence,
            "epoch": self.epoch,
            "resourceversion": self.resourceversion,
            "correlationid": self.correlationid,
            "data": self.data,
        }
        if self.operationid:
            envelope["operationid"] = self.operationid
        if self.severity:
            envelope["severity"] = self.severity
        return f"id: {self.epoch}:{self.sequence}\nevent: {self.type}\ndata: {json.dumps(envelope, ensure_ascii=False)}\n\n"


@dataclass
class EventLog:
    # 进程内事件日志 + 订阅者队列。保留最近 N 条用于短暂断连重放。
    epoch: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    _seq: int = 0
    _events: list[Event] = field(default_factory=list)
    _subscribers: list[asyncio.Queue[Event]] = field(default_factory=list)
    _retention: int = 1024  # 保留最近 1024 条;超窗口游标返回 410

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def emit(
        self,
        *,
        type_: str,
        subject: str,
        data: dict[str, Any],
        resource_ref: ResourceRef,
        correlation_id: str,
        operation_id: str | None = None,
        severity: str = "info",
        resource_version: str | None = None,
    ) -> Event:
        seq = self._next_seq()
        ev = Event(
            id=uuid.uuid4().hex,
            type=type_,
            source="urn:ai-agent-desktop:control-plane",
            subject=subject,
            time=utcnow(),
            sequence=seq,
            epoch=self.epoch,
            resourceversion=resource_version or f"seq:{seq}",
            correlationid=correlation_id,
            data=data,
            operationid=operation_id,
            severity=severity,
        )
        self._events.append(ev)
        if len(self._events) > self._retention:
            self._events = self._events[-self._retention :]
        for q in list(self._subscribers):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:  # pragma: no cover
                pass
        return ev

    def subscribe(self, last_event_id: str | None) -> tuple[asyncio.Queue[Event], list[Event]]:
        # 返回订阅队列 + 从 last_event_id 之后的历史事件(用于重放)。游标过期抛 CursorExpired。
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=256)
        replay: list[Event] = []
        if last_event_id:
            try:
                epoch_part, seq_part = last_event_id.split(":")
                seq = int(seq_part)
            except ValueError:
                raise CursorExpired() from None
            if epoch_part != self.epoch:
                raise CursorExpired() from None
            replay = [e for e in self._events if e.sequence > seq]
        self._subscribers.append(queue)
        return queue, replay

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)


class CursorExpired(Exception):
    # 对应 410 EVENT_CURSOR_EXPIRED
    pass

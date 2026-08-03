import pytest

from control_plane.application.event_log import CursorExpired, EventLog
from control_plane.domain.models import ResourceRef


def _ref() -> ResourceRef:
    return ResourceRef(kind="system", id="local")


def test_emit_records_sequence_and_epoch():
    log = EventLog()
    e1 = log.emit(
        type_="com.aiagentdesktop.operation.started.v1",
        subject="op:1",
        data={},
        resource_ref=_ref(),
        correlation_id="c",
    )
    e2 = log.emit(
        type_="com.aiagentdesktop.operation.completed.v1",
        subject="op:1",
        data={},
        resource_ref=_ref(),
        correlation_id="c",
    )
    assert e1.sequence == 1 and e2.sequence == 2
    assert e1.epoch == e2.epoch == log.epoch


def test_replay_from_cursor():
    log = EventLog()
    e1 = log.emit(
        type_="com.aiagentdesktop.operation.started.v1",
        subject="s",
        data={},
        resource_ref=_ref(),
        correlation_id="c",
    )
    log.emit(
        type_="com.aiagentdesktop.operation.completed.v1",
        subject="s",
        data={},
        resource_ref=_ref(),
        correlation_id="c",
    )
    _q, replay = log.subscribe(f"{log.epoch}:{e1.sequence}")
    assert [e.sequence for e in replay] == [2]
    assert replay[0].type.endswith("operation.completed.v1")


def test_stale_cursor_raises():
    log = EventLog()
    with pytest.raises(CursorExpired):
        log.subscribe("staleepoch:1")
    with pytest.raises(CursorExpired):
        log.subscribe("bad-format")


def test_to_sse_format_has_envelope_and_operationid():
    log = EventLog()
    ev = log.emit(
        type_="com.aiagentdesktop.plan.generated.v1",
        subject="plan:p1",
        data={"plan_id": "p1", "actions": 1},
        resource_ref=_ref(),
        correlation_id="c",
        operation_id="op1",
    )
    s = ev.to_sse()
    assert s.startswith(f"id: {log.epoch}:{ev.sequence}\n")
    assert "event: com.aiagentdesktop.plan.generated.v1\n" in s
    assert "operationid" in s
    assert "specversion" in s


def test_operation_event_type_requires_operationid():
    # 契约:event-envelope allOf 要求 type 以 operation. 开头时 operationid 必填
    log = EventLog()
    ev = log.emit(
        type_="com.aiagentdesktop.operation.started.v1",
        subject="op:1",
        data={},
        resource_ref=_ref(),
        correlation_id="c",
        operation_id="op1",
    )
    assert ev.operationid == "op1"

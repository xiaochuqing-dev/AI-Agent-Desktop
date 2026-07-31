from control_plane.application.discovery_service import DiscoveryService
from control_plane.application.event_log import EventLog
from control_plane.application.operation_store import OperationStore
from control_plane.domain.models import ResourceRef
from control_plane.infrastructure.config import Settings
from control_plane.persistence.session import Database

from .fakes import make_fake_adapters


def test_discovery_run_produces_report_and_events(tmp_path):
    settings = Settings(data_dir=str(tmp_path))
    db = Database(settings)
    events = EventLog()
    adapters = make_fake_adapters()
    with db.session() as s:
        store = OperationStore(s)
        op, _ = store.create(
            kind="discovery",
            target_ref=ResourceRef(kind="system", id="local"),
            idempotency_key="k" * 16,
            method="POST",
            resource="/discovery",
            body=b"",
        )
        svc = DiscoveryService(adapters, store, events)
        report = svc.run(op.operation_id, "corr-1")

    assert report.system_modified is False
    assert report.redaction_applied is True
    assert len(report.components) == 2
    assert report.dry_run_plan.execute is False
    assert report.dry_run_plan.status == "planned"
    # dry-run 计划至少有一条动作(healthy 组件无需动作,但 missing 组件应有 install/configure)
    assert len(report.dry_run_plan.actions) >= 1
    types = {e.type for e in events._events}
    assert "com.aiagentdesktop.operation.started.v1" in types
    assert "com.aiagentdesktop.operation.completed.v1" in types
    assert "com.aiagentdesktop.component.discovered.v1" in types
    assert "com.aiagentdesktop.scan.progress.v1" in types
    assert "com.aiagentdesktop.plan.generated.v1" in types


def test_repeated_scan_idempotent_components(tmp_path):
    # 同一组件重复扫描得到稳定 component_id,无随机差异
    settings = Settings(data_dir=str(tmp_path))
    db = Database(settings)
    events = EventLog()
    adapters = make_fake_adapters()
    with db.session() as s:
        store = OperationStore(s)
        op1, _ = store.create(
            kind="discovery",
            target_ref=ResourceRef(kind="system", id="local"),
            idempotency_key="k" * 16,
            method="POST",
            resource="/discovery",
            body=b"",
        )
        svc = DiscoveryService(adapters, store, events)
        r1 = svc.run(op1.operation_id, "c1")
        ids1 = {c.component_id for c in r1.components}

    with db.session() as s:
        store = OperationStore(s)
        op2, _ = store.create(
            kind="discovery",
            target_ref=ResourceRef(kind="system", id="local"),
            idempotency_key="z" * 16,
            method="POST",
            resource="/discovery",
            body=b"",
        )
        svc = DiscoveryService(adapters, store, events)
        r2 = svc.run(op2.operation_id, "c2")
        ids2 = {c.component_id for c in r2.components}

    assert ids1 == ids2 == {"fake-healthy", "fake-mmissing" if False else "fake-missing"}

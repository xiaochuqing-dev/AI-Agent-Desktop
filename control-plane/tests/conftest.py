import pytest

TEST_TOKEN = "test-token-0123456789abcdef0123456789abcdef"


@pytest.fixture
def client(tmp_path, monkeypatch):
    # 懒加载:避免无 DB 依赖的测试因导入 platformdirs 失败
    from fastapi.testclient import TestClient

    from control_plane.api.app import create_app
    from control_plane.infrastructure.config import Settings

    from .fakes import make_fake_adapters

    monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", TEST_TOKEN)
    settings = Settings(data_dir=str(tmp_path))
    app = create_app(settings, adapters=make_fake_adapters())
    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.headers.update({"Authorization": f"Bearer {TEST_TOKEN}"})
        yield c


def wait_for_operation(client, operation_id: str, timeout: float = 10.0) -> dict:
    # 轮询 Operation 直到终态
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/v1/operations/{operation_id}")
        assert r.status_code == 200
        op = r.json()
        if op["status"] in ("succeeded", "failed", "canceled"):
            return op
        time.sleep(0.05)
    raise AssertionError(f"operation {operation_id} 未在 {timeout}s 内完成")


@pytest.fixture
def managed_runtime_environment(tmp_path, monkeypatch):
    from control_plane.application.event_log import EventLog
    from control_plane.configuration.service import CcConnectConfigurationService
    from control_plane.infrastructure.config import Settings
    from control_plane.installer.models import (
        InstallConfirmationRequest,
        InstallPlanRequest,
    )
    from control_plane.installer.service import CcConnectInstaller
    from control_plane.installer.version_store import ManagedVersionStore
    from control_plane.lifecycle.managed_process import ManagedProcessService
    from control_plane.lifecycle.models import (
        OwnershipConfirmationRequest,
        OwnershipPlanRequest,
    )
    from control_plane.lifecycle.port_ownership import PortOwnershipInspector
    from control_plane.persistence.session import Database

    from .installer_helpers import write_test_bundle

    bundle, manifest = write_test_bundle(tmp_path / "可信 产物 (bundle)")
    settings = Settings(
        data_dir=str(tmp_path / "隔离 LocalAppData 中文 (运行)"),
        trusted_artifact_dir=str(bundle),
    )
    database = Database(settings)

    def successful_probe(_path, probed_manifest, *, cancel_check=None, **_kwargs):
        if cancel_check:
            cancel_check()
        return f"{probed_manifest.version} {probed_manifest.source_commit[:7]}"

    monkeypatch.setattr(
        "control_plane.installer.service.run_isolated_version_probe", successful_probe
    )
    installer = CcConnectInstaller(settings, database, EventLog())
    install_plan = installer.create_plan(
        InstallPlanRequest(
            source_ref="trusted-local-bundle",
            expected_digest=f"sha256:{manifest.artifact_sha256}",
        )
    )
    install_confirmation = InstallConfirmationRequest(
        requested_version=install_plan.version,
        source_ref=install_plan.source.source_ref,
        expected_digest=f"sha256:{install_plan.sha256}",
        confirm=True,
        plan_id=install_plan.plan_id,
        plan_digest=install_plan.plan_digest,
        confirmation=True,
    )
    install_operation, _ = installer.confirm_install(
        install_confirmation,
        idempotency_key="runtime-install-key",
        body=install_confirmation.model_dump_json().encode(),
    )
    installer.execute_install(install_operation.operation_id, install_plan.plan_id, "test")
    version_store = ManagedVersionStore(installer.layout, database)
    port_inspector = PortOwnershipInspector()
    configuration = CcConnectConfigurationService(
        database,
        installer.layout,
        version_store=version_store,
        port_inspector=port_inspector,
        external_conflict_detector=lambda: False,
    )
    lifecycle = ManagedProcessService(
        database,
        installer.layout,
        configuration,
        version_store=version_store,
        port_inspector=port_inspector,
        external_detector=lambda: False,
    )
    owner_plan = lifecycle.create_ownership_plan(OwnershipPlanRequest())
    owner_confirmation = OwnershipConfirmationRequest(
        plan_id=owner_plan.plan_id,
        plan_digest=owner_plan.plan_digest,
        current_management_owner=owner_plan.current_management_owner,
        current_lifecycle_owner=owner_plan.current_lifecycle_owner,
        confirmation=True,
    )
    owner_operation, _ = lifecycle.confirm_ownership_plan(
        owner_confirmation,
        idempotency_key="runtime-owner-key",
        body=owner_confirmation.model_dump_json().encode(),
    )
    lifecycle.execute_ownership_handoff(owner_operation.operation_id, owner_plan.plan_id)
    yield {
        "settings": settings,
        "database": database,
        "installer": installer,
        "manifest": manifest,
        "version_store": version_store,
        "port_inspector": port_inspector,
        "configuration": configuration,
        "lifecycle": lifecycle,
    }
    database.engine.dispose()

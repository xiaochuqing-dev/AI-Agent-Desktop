from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from control_plane.api.app import create_app
from control_plane.infrastructure.config import Settings

from .conftest import TEST_TOKEN, wait_for_operation
from .fakes import make_fake_adapters
from .installer_helpers import write_test_bundle


def _client(tmp_path, monkeypatch, *, fault_injector=None):
    bundle, manifest = write_test_bundle(tmp_path / "API 可信产物")

    def successful_probe(_path, probed_manifest, *, cancel_check=None, **_kwargs):
        if cancel_check:
            cancel_check()
        return f"{probed_manifest.version} {probed_manifest.source_commit[:7]}"

    monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", TEST_TOKEN)
    monkeypatch.setattr(
        "control_plane.installer.service.run_isolated_version_probe", successful_probe
    )
    app = create_app(
        Settings(
            data_dir=str(tmp_path / "API LocalAppData (隔离)"),
            trusted_artifact_dir=str(bundle),
        ),
        adapters=make_fake_adapters(),
        installer_fault_injector=fault_injector,
    )
    client = TestClient(app, base_url="http://127.0.0.1")
    client.headers.update({"Authorization": f"Bearer {TEST_TOKEN}"})
    return client, manifest


def _plan(client, manifest):
    response = client.post(
        "/api/v1/components/cc-connect/install-plan",
        json={
            "source_ref": "trusted-local-bundle",
            "expected_digest": f"sha256:{manifest.artifact_sha256}",
        },
    )
    assert response.status_code == 201
    return response.json()


def _confirmation(plan):
    return {
        "version_policy": "exact",
        "requested_version": plan["version"],
        "source_ref": plan["source"]["source_ref"],
        "expected_digest": f"sha256:{plan['sha256']}",
        "confirm": True,
        "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"],
        "confirmation": True,
    }


def test_install_api_plan_confirmation_operation_events_and_versions(tmp_path, monkeypatch):
    client, manifest = _client(tmp_path, monkeypatch)
    with client:
        plan = _plan(client, manifest)
        response = client.post(
            "/api/v1/components/cc-connect:install",
            json=_confirmation(plan),
            headers={"Idempotency-Key": "api-install-key-0001"},
        )
        assert response.status_code == 202
        operation_id = response.json()["operation_id"]
        completed = wait_for_operation(client, operation_id)
        assert completed["status"] == "succeeded"
        assert completed["result"]["artifact_sha256"] == manifest.artifact_sha256

        retry = client.post(
            "/api/v1/components/cc-connect:install",
            json=_confirmation(plan),
            headers={"Idempotency-Key": "api-install-key-0001"},
        )
        assert retry.status_code == 202
        assert retry.json()["operation_id"] == operation_id
        events = client.get(f"/api/v1/operations/{operation_id}/events")
        assert events.status_code == 200
        assert events.json()[-1]["phase"] == "completed"
        versions = client.get("/api/v1/components/cc-connect/managed-versions")
        assert versions.status_code == 200
        assert versions.json()[0]["current"] is True


def test_install_api_rejects_unbound_confirmation_and_other_components(tmp_path, monkeypatch):
    client, manifest = _client(tmp_path, monkeypatch)
    with client:
        plan = _plan(client, manifest)
        confirmation = _confirmation(plan)
        confirmation["plan_digest"] = "sha256:" + "0" * 64
        response = client.post(
            "/api/v1/components/cc-connect:install",
            json=confirmation,
            headers={"Idempotency-Key": "api-mismatch-key-01"},
        )
        assert response.status_code == 409
        assert response.json()["code"] == "INSTALL_CONFIRMATION_MISMATCH"
        unsupported = client.post(
            "/api/v1/components/hermes:install",
            headers={"Idempotency-Key": "api-unsupported-01"},
        )
        assert unsupported.status_code == 501
        assert unsupported.json()["code"] == "CAPABILITY_UNSUPPORTED"


def test_cancel_api_is_persistent_idempotent_and_stops_at_checkpoint(tmp_path, monkeypatch):
    acquisition_entered = threading.Event()
    release_acquisition = threading.Event()

    def pause_acquisition(phase: str, _operation_id: str) -> None:
        if phase == "acquiring":
            acquisition_entered.set()
            release_acquisition.wait(timeout=5)

    client, manifest = _client(tmp_path, monkeypatch, fault_injector=pause_acquisition)
    with client:
        plan = _plan(client, manifest)
        response = client.post(
            "/api/v1/components/cc-connect:install",
            json=_confirmation(plan),
            headers={"Idempotency-Key": "api-cancel-install"},
        )
        operation_id = response.json()["operation_id"]
        assert acquisition_entered.wait(timeout=5)
        cancel_body = {"reason": "automated safe-checkpoint test"}
        canceled = client.post(
            f"/api/v1/operations/{operation_id}:cancel",
            json=cancel_body,
            headers={"Idempotency-Key": "api-cancel-request"},
        )
        assert canceled.status_code == 202
        assert canceled.json()["status"] == "cancel_requested"
        release_acquisition.set()
        completed = wait_for_operation(client, operation_id)
        assert completed["status"] == "canceled"
        retry = client.post(
            f"/api/v1/operations/{operation_id}:cancel",
            json=cancel_body,
            headers={"Idempotency-Key": "api-cancel-request"},
        )
        assert retry.status_code == 202
        assert retry.json()["status"] == "canceled"
        deadline = time.time() + 2
        while time.time() < deadline:
            events = client.get(f"/api/v1/operations/{operation_id}/events").json()
            if any(item["event_type"].endswith("cancel_requested.v1") for item in events):
                break
            time.sleep(0.01)
        assert any(item["event_type"].endswith("cancel_requested.v1") for item in events)

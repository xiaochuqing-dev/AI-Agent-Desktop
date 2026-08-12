from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from control_plane.api.app import create_app
from control_plane.credentials.windows_backend import InMemorySecretBackend
from control_plane.infrastructure.config import Settings

from .conftest import wait_for_operation
from .fakes import make_fake_adapters, make_fake_agent_detection
from .telegram_helpers import SLOTS, TOKENS, FakeTelegramClient

CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "control-plane-v1"
    / "onboarding.schema.json"
)


def test_onboarding_and_dashboard_snapshots_are_read_only_contracts(client):
    onboarding = client.get("/api/v1/onboarding/snapshot")
    dashboard = client.get("/api/v1/dashboard/snapshot")
    availability = client.get("/api/v1/telegram/client-availability")
    assert onboarding.status_code == 200
    assert dashboard.status_code == 200
    assert availability.status_code == 200
    body = onboarding.json()
    assert body["current_step"] in {1, 2}
    assert len(body["agents"]) == 3
    assert '"secret"' not in onboarding.text.lower()
    assert '"bind_code"' not in onboarding.text.lower()
    assert "my_chat_member" not in onboarding.text

    with CONTRACT_PATH.open(encoding="utf-8") as stream:
        contract = json.load(stream)
    validator = Draft202012Validator(contract)
    validator.validate(body)
    validator.validate(dashboard.json())
    validator.validate(availability.json())


def test_onboarding_requires_agents_and_runtime_not_only_binding_and_config(client):
    body = client.get("/api/v1/onboarding/snapshot").json()
    assert all(agent["installed"] is True for agent in body["agents"])
    assert all(agent["acceptable"] is True for agent in body["agents"])
    connected = {agent["slot"]: agent["connected"] for agent in body["agents"]}
    assert connected == {"hermes": None, "claude": False, "codex": False}
    assert body["runtime"]["ready"] is False
    assert body["onboarding_complete"] is False
    assert (
        next(item for item in body["checklist"] if item["key"] == "runtime")["status"] != "complete"
    )


def test_explicit_agent_refresh_is_redacted_and_stable_contract(client):
    response = client.get("/api/v1/agents?refresh=true")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    assert all(item["acceptable"] is True for item in body)
    assert "executable_path" not in response.text


def test_resume_endpoint_reissues_links_without_snapshot_or_database_leak(tmp_path, monkeypatch):
    bearer = "resume-api-token-0123456789"
    monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", bearer)
    app = create_app(
        Settings(data_dir=str(tmp_path)),
        adapters=make_fake_adapters(),
        credential_backend=InMemorySecretBackend(),
        telegram_client=FakeTelegramClient(),  # type: ignore[arg-type]
        hermes_path_lookup=lambda _name: None,
        agent_detection_service=make_fake_agent_detection(),
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.headers["Authorization"] = f"Bearer {bearer}"
        for slot in SLOTS:
            stored = client.put(
                f"/api/v1/credentials/telegram/{slot}",
                headers={"Idempotency-Key": f"resume-credential-{slot}-0001"},
                json={"secret": TOKENS[slot]},
            )
            assert stored.status_code == 201
            verified = client.post(
                f"/api/v1/telegram/bots/{slot}:verify",
                headers={"Idempotency-Key": f"resume-verify-{slot}-0001"},
            )
            assert verified.status_code == 202
            assert (
                wait_for_operation(client, verified.json()["operation_id"])["status"] == "succeeded"
            )

        created_response = client.post(
            "/api/v1/telegram/bindings",
            json={"expires_in_seconds": 900, "runtimes_stopped_confirmation": True},
        )
        assert created_response.status_code == 201
        created = created_response.json()
        snapshot = client.get("/api/v1/onboarding/snapshot")
        assert snapshot.json()["binding"]["session_id"] == created["session_id"]
        assert "bind_code" not in snapshot.text
        assert "private_deep_links" not in snapshot.text

        resumed_response = client.post(
            f"/api/v1/telegram/bindings/{created['session_id']}:resume",
            json={"expires_in_seconds": 900, "runtimes_stopped_confirmation": True},
        )
        assert resumed_response.status_code == 200
        resumed = resumed_response.json()
        assert resumed["session_id"] == created["session_id"]
        assert resumed["bind_code"] != created["bind_code"]
        assert resumed["private_deep_links"] != created["private_deep_links"]
        assert resumed["revision"] == created["revision"] + 1

        after = client.get("/api/v1/onboarding/snapshot")
        assert "bind_code" not in after.text
        assert "private_deep_links" not in after.text

    database_bytes = (tmp_path / "control_plane.db").read_bytes()
    assert created["bind_code"].encode() not in database_bytes
    assert resumed["bind_code"].encode() not in database_bytes

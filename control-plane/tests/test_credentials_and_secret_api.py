from __future__ import annotations

import json

from fastapi.testclient import TestClient

from control_plane.api.app import create_app
from control_plane.credentials.models import CredentialStatus
from control_plane.credentials.service import CredentialService
from control_plane.credentials.windows_backend import InMemorySecretBackend
from control_plane.infrastructure.config import Settings
from control_plane.persistence.session import Database

from .conftest import wait_for_operation
from .fakes import make_fake_adapters
from .telegram_helpers import TOKENS, FakeTelegramClient


def test_credential_put_replace_delete_and_metadata_only(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    backend = InMemorySecretBackend()
    service = CredentialService(database, backend)
    reference = "telegram/claude-bot-token"

    created = service.put(reference, "synthetic-one", operation_id="put-one")
    assert created.revision == 1
    assert created.status == CredentialStatus.AVAILABLE
    assert "synthetic-one" not in created.model_dump_json()

    replaced = service.replace(reference, "synthetic-two", operation_id="replace-one")
    assert replaced.revision == 2
    with service.resolve_for_operation(reference) as value:
        assert value == "synthetic-two"

    deleted = service.delete(reference, operation_id="delete-one")
    assert deleted.revision == 3
    assert deleted.status == CredentialStatus.MISSING
    assert service.get(reference).status == CredentialStatus.MISSING


def test_credential_status_distinguishes_backend_states(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    backend = InMemorySecretBackend()
    service = CredentialService(database, backend)
    reference = "telegram/codex-bot-token"
    for status in (
        CredentialStatus.INACCESSIBLE,
        CredentialStatus.BACKEND_UNAVAILABLE,
        CredentialStatus.CORRUPT,
        CredentialStatus.UNKNOWN,
    ):
        backend.forced_status[reference] = status
        assert service.get(reference).status == status


def test_secret_api_never_echoes_or_persists_request_body(tmp_path, monkeypatch):
    token = "synthetic-secret-never-persist-123456"
    monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "local-api-token-1234567890")
    backend = InMemorySecretBackend()
    app = create_app(
        Settings(data_dir=str(tmp_path)),
        adapters=make_fake_adapters(),
        credential_backend=backend,
        telegram_client=FakeTelegramClient(),  # type: ignore[arg-type]
        hermes_path_lookup=lambda _name: None,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.headers["Authorization"] = "Bearer local-api-token-1234567890"
        response = client.put(
            "/api/v1/credentials/telegram/claude",
            headers={"Idempotency-Key": "credential-secret-put-0001"},
            json={"secret": token},
        )
        assert response.status_code == 201
        assert token not in response.text
        assert response.json()["reference_id"] == "telegram/claude-bot-token"
        assert response.headers["X-Operation-ID"]

        invalid = client.put(
            "/api/v1/credentials/telegram/codex",
            headers={"Idempotency-Key": "credential-secret-put-0002"},
            json={"secret": token * 200},
        )
        assert invalid.status_code == 422
        assert token not in invalid.text

    database_bytes = (tmp_path / "control_plane.db").read_bytes()
    assert token.encode() not in database_bytes
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.name != "control_plane.db":
            assert token.encode() not in path.read_bytes()


def test_openapi_and_bot_verification_operation_use_non_secret_contracts(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "local-api-token-1234567890")
    backend = InMemorySecretBackend()
    app = create_app(
        Settings(data_dir=str(tmp_path)),
        adapters=make_fake_adapters(),
        credential_backend=backend,
        telegram_client=FakeTelegramClient(),  # type: ignore[arg-type]
        hermes_path_lookup=lambda _name: None,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.headers["Authorization"] = "Bearer local-api-token-1234567890"
        openapi = client.get("/api/v1/openapi.json").json()
        for path in (
            "/api/v1/credentials/telegram/{slot}",
            "/api/v1/telegram/bots/{slot}:verify",
            "/api/v1/telegram/bindings",
            "/api/v1/components/{component_id}/native-configuration-plans",
            "/api/v1/components/hermes/telegram-configuration-plans",
        ):
            assert path in openapi["paths"]
        mutation_schema = openapi["components"]["schemas"]["CredentialMutationRequest"]
        assert mutation_schema["properties"]["secret"]["writeOnly"] is True

        put = client.put(
            "/api/v1/credentials/telegram/claude",
            headers={"Idempotency-Key": "credential-verify-put-0001"},
            json={"secret": TOKENS["claude"]},
        )
        assert put.status_code == 201
        verify = client.post(
            "/api/v1/telegram/bots/claude:verify",
            headers={"Idempotency-Key": "telegram-verify-operation-0001"},
        )
        assert verify.status_code == 202
        operation_id = verify.json()["operation_id"]
        operation = wait_for_operation(client, operation_id)
        assert operation["status"] == "succeeded"
        assert operation["result"]["username"] == "aiad_claude_bot"
        assert TOKENS["claude"] not in json.dumps(operation)

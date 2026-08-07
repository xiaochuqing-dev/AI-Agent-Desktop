from __future__ import annotations


def test_observability_routes_are_redacted_and_offline_by_default(client):
    links = client.get("/api/v1/observability/links")
    assert links.status_code == 200
    payload = links.json()
    assert len(payload) == 6
    assert [item["link_id"] for item in payload] == [
        "hermes.private",
        "hermes.group",
        "claude.private",
        "claude.group",
        "codex.private",
        "codex.group",
    ]
    assert all(item["status"] == "credential_missing" for item in payload)

    synthetic = client.post("/api/v1/observability/synthetic-e2e:run")
    assert synthetic.status_code == 200
    assert len(synthetic.json()) == 6
    assert all(item["evidence_level"] == "synthetic" for item in synthetic.json())

    isolation = client.post("/api/v1/observability/session-isolation:probe")
    assert isolation.status_code == 200
    assert isolation.json()["status"] == "passed"
    assert isolation.json()["evidence_level"] == "synthetic"

    policy = client.get("/api/v1/telegram/network-policy")
    assert policy.status_code == 200
    assert policy.json()["mode"] == "direct"
    assert policy.json()["effective_proxy"] is None


def test_observability_contract_paths_are_registered(client):
    paths = set(client.app.openapi()["paths"])
    assert "/api/v1/observability/links" in paths
    assert "/api/v1/observability/links/{link_id}/e2e-plans" in paths
    assert "/api/v1/observability/e2e-plans/{plan_id}:confirm" in paths
    assert "/api/v1/observability/e2e-runs/{run_id}/response" in paths
    assert "/api/v1/observability/session-isolation:probe" in paths

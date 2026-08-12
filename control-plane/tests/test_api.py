from .conftest import wait_for_operation


def test_events_route_registered(client):
    # SSE 端点已注册;无限流式响应在 ASGITransport 下关闭会死锁,
    # 故成功路径的事件结构、重放与 410 由 test_event_log 与 test_events_cursor_expired 覆盖。
    routes = {getattr(r, "path", "") for r in client.app.routes}
    assert "/api/v1/events" in routes


def test_system_endpoint(client):
    r = client.get("/api/v1/system")
    assert r.status_code == 200
    info = r.json()
    assert info["api_version"] == "v1"
    assert info["contract_version"] == "1.0.0"
    assert info["instance_id"].startswith("cp-")


def test_system_unauth_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("CONTROL_PLANE_API_TOKEN", raising=False)
    from fastapi.testclient import TestClient

    from control_plane.api.app import create_app
    from control_plane.infrastructure.config import Settings

    settings = Settings(data_dir=str(tmp_path))
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        r = c.get("/api/v1/system")
        assert r.status_code == 401


def test_discovery_and_readiness(client):
    r = client.post(
        "/api/v1/discovery:run",
        headers={"Idempotency-Key": "akey-" + "x" * 11},
    )
    assert r.status_code == 202
    assert "Location" in r.headers
    op_id = r.json()["operation_id"]
    op = wait_for_operation(client, op_id)
    assert op["status"] == "succeeded"

    rr = client.get("/api/v1/readiness")
    assert rr.status_code == 200
    report = rr.json()
    assert report["system_modified"] is False
    assert report["redaction_applied"] is True
    assert report["dry_run_plan"]["execute"] is False
    assert len(report["components"]) == 2
    assert len(report["blockers"]) == 1
    assert report["blockers"][0]["code"] == "COMPONENT_NOT_INSTALLED"

    diagnostics = client.get("/api/v1/diagnostics")
    assert diagnostics.status_code == 200
    diagnostic_codes = {item["code"] for item in diagnostics.json()}
    assert {item["code"] for item in report["blockers"] + report["warnings"]}.issubset(
        diagnostic_codes
    )
    assert "CC_CONNECT_RUNTIME_NOT_READY" in diagnostic_codes

    rc = client.get("/api/v1/components")
    assert rc.status_code == 200
    assert len(rc.json()) == 2


def test_component_detail_and_not_found(client):
    r = client.post("/api/v1/discovery:run", headers={"Idempotency-Key": "bkey-" + "y" * 11})
    op_id = r.json()["operation_id"]
    wait_for_operation(client, op_id)
    r = client.get("/api/v1/components/fake-healthy")
    assert r.status_code == 200
    r2 = client.get("/api/v1/components/does-not-exist")
    assert r2.status_code == 404


def test_lifecycle_unsupported(client):
    for action in ("start", "stop", "restart", "install"):
        payload = (
            {"configuration_revision": 1, "confirmation": True} if action != "install" else None
        )
        r = client.post(
            f"/api/v1/components/hermes:{action}",
            headers={"Idempotency-Key": "k" * 16},
            json=payload,
        )
        assert r.status_code == 501
        assert r.json()["code"] == "CAPABILITY_UNSUPPORTED"


def test_operations_list(client):
    r = client.get("/api/v1/operations")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_managed_runtime_routes_report_truthful_unconfigured_state(client):
    runtime = client.get("/api/v1/components/cc-connect/lifecycle")
    assert runtime.status_code == 200
    assert runtime.json()["observed_state"] == "unconfigured"
    assert runtime.json()["lifecycle_owner"] == "none"
    assert runtime.json()["health"]["deep_health"] == "unsupported"

    plan = client.post(
        "/api/v1/components/cc-connect/configuration-plans",
        json={},
    )
    assert plan.status_code == 409
    assert plan.json()["code"] == "MANAGED_VERSION_NOT_INSTALLED"


def test_start_api_is_persisted_and_fails_closed_without_configuration(client):
    response = client.post(
        "/api/v1/components/cc-connect:start",
        headers={"Idempotency-Key": "runtime-start-api-key"},
        json={"configuration_revision": 1, "confirmation": True},
    )
    assert response.status_code == 202
    completed = wait_for_operation(client, response.json()["operation_id"])
    assert completed["status"] == "failed"
    assert completed["error"]["code"] == "MANAGED_VERSION_NOT_INSTALLED"


def test_health_check_has_its_own_persisted_operation_kind(client):
    response = client.post(
        "/api/v1/components/cc-connect/health:check",
        headers={"Idempotency-Key": "runtime-health-api-key"},
        json={"configuration_revision": 1, "confirmation": True},
    )
    assert response.status_code == 202
    assert response.json()["kind"] == "cc_connect_lifecycle_health"
    completed = wait_for_operation(client, response.json()["operation_id"])
    assert completed["status"] == "succeeded"
    assert completed["result"]["observed_state"] == "unconfigured"


def test_update_and_cc_switch_boundaries_do_not_overreport(client):
    switch = client.get("/api/v1/external-tools/cc-switch")
    assert switch.status_code == 200
    capabilities = {item["capability"]: item["status"] for item in switch.json()["capabilities"]}
    assert capabilities["install"] == "unknown"
    assert capabilities["update"] == "unknown"

    hermes = client.get(
        "/api/v1/components/hermes/update-assessment",
        params={"requested_version": "future"},
    )
    assert hermes.status_code == 200
    assert hermes.json()["status"] == "unsupported"
    assert hermes.json()["automatic_update_performed"] is False


def test_events_cursor_expired(client):
    # 旧 epoch 游标应返回 410
    r = client.get("/api/v1/events", headers={"Last-Event-ID": "staleepoch:1"})
    assert r.status_code == 410
    assert r.json()["code"] == "EVENT_CURSOR_EXPIRED"


def test_response_has_no_real_secret(client):
    r = client.post("/api/v1/discovery:run", headers={"Idempotency-Key": "ckey-" + "z" * 11})
    op_id = r.json()["operation_id"]
    wait_for_operation(client, op_id)
    import re

    for path in ("/api/v1/readiness", "/api/v1/components", "/api/v1/operations"):
        body = client.get(path).text
        assert "sk-ant-" not in body
        # 不应出现 Telegram bot token 形态
        assert not re.search(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b", body)

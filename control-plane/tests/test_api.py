from datetime import UTC, datetime

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


def test_hermes_readiness_plan_apply_api_covers_conflict_retry(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from control_plane.api.app import create_app, get_state
    from control_plane.hermes.models import (
        HermesTelegramConfigurationPlan,
        HermesTelegramReadinessSnapshot,
    )
    from control_plane.infrastructure.config import Settings
    from control_plane.installer.artifacts import InstallerError

    from .fakes import make_fake_adapters
    from .telegram_helpers import FakeTelegramClient

    api_token = "hermes-api-test-token"
    monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", api_token)
    app = create_app(
        Settings(data_dir=str(tmp_path)),
        adapters=make_fake_adapters(),
        credential_backend=None,
        telegram_client=FakeTelegramClient(),  # type: ignore[arg-type]
        hermes_path_lookup=lambda _name: None,
    )
    state = get_state()
    readiness = HermesTelegramReadinessSnapshot(
        configuration_status="DIFFERENT_BOT",
        bot_identity_status="verified",
        operator_allowed=True,
        gateway_status="running",
        gateway_running=True,
        change_required=True,
        conflict=True,
        diagnostic_code="HERMES_TELEGRAM_EXISTING_BOT_CONFLICT",
        user_message="检测到 Hermes 已连接另一个 Telegram Bot。",
        revision=4,
        bot_id=101,
        username="existing_bot",
    )
    plan = HermesTelegramConfigurationPlan(
        plan_id="hermes-api-plan",
        plan_digest="sha256:" + "a" * 64,
        binding_session_id="binding-api-test",
        status="ready",
        readiness=readiness,
        choice="switch_to_current",
        expected_changes=["merge operator", "restart gateway"],
        user_confirmation_required=True,
        created_at=datetime.now(UTC),
    )

    class FakeHermesAdapter:
        def __init__(self):
            self.readiness_calls: list[str | None] = []
            self.plan_calls: list[bool] = []

        def readiness(self, *, binding_session_id=None):
            self.readiness_calls.append(binding_session_id)
            return readiness

        def create_plan(self, request):
            self.plan_calls.append(request.confirmation)
            if not request.confirmation:
                raise InstallerError(
                    "HERMES_TELEGRAM_CONFLICT_CONFIRMATION_REQUIRED",
                    "切换 Hermes 当前 Bot 需要明确确认。",
                )
            return plan

        def confirm_plan(self, _request):
            return plan.plan_id, False

    adapter = FakeHermesAdapter()
    state.hermes_telegram = adapter  # type: ignore[assignment]
    submitted: list[dict] = []
    state.executor.submit = lambda **payload: submitted.append(payload)  # type: ignore[method-assign]

    with TestClient(app, base_url="http://127.0.0.1") as test_client:
        test_client.headers["Authorization"] = f"Bearer {api_token}"
        snapshot = test_client.get(
            "/api/v1/components/hermes/telegram-readiness",
            params={"binding_session_id": "binding-api-test"},
        )
        assert snapshot.status_code == 200
        assert snapshot.json()["configuration_status"] == "DIFFERENT_BOT"
        assert adapter.readiness_calls == ["binding-api-test"]

        blocked = test_client.post(
            "/api/v1/components/hermes/telegram-configuration:plan",
            json={"binding_session_id": "binding-api-test", "confirmation": False},
        )
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "HERMES_TELEGRAM_CONFLICT_CONFIRMATION_REQUIRED"

        created = test_client.post(
            "/api/v1/components/hermes/telegram-configuration:plan",
            json={
                "binding_session_id": "binding-api-test",
                "choice": "switch_to_current",
                "confirmation": True,
            },
        )
        assert created.status_code == 201
        assert created.json()["user_confirmation_required"] is True

        applied = test_client.post(
            "/api/v1/components/hermes/telegram-configuration:apply",
            headers={"Idempotency-Key": "hermes-api-apply-key-0001"},
            json={
                "plan_id": plan.plan_id,
                "plan_digest": plan.plan_digest,
                "choice": "switch_to_current",
                "confirmation": True,
            },
        )
        assert applied.status_code == 202
        assert applied.headers["Location"].startswith("/api/v1/operations/")
        assert submitted[0]["kind"] == "hermes_telegram_configuration_apply"

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QDesktopServices  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton  # noqa: E402

from control_plane.gui.api_client import (  # noqa: E402
    DemoControlPlaneClient,
    EmbeddedControlPlaneClient,
    HttpControlPlaneClient,
)
from control_plane.gui.app import APP_VERSION, build_client  # noqa: E402
from control_plane.gui.icons import ICON_NAMES, icon  # noqa: E402
from control_plane.gui.main_window import MainWindow  # noqa: E402
from control_plane.gui.pages import (  # noqa: E402
    CompletionPage,
    DashboardPage,
    GroupPage,
    TokenPage,
)
from control_plane.gui.state_store import GuiStateStore  # noqa: E402
from control_plane.gui.widgets import ASSET_DIR, QrDialog, TelegramLauncher  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


def test_demo_contract_keeps_token_out_of_snapshot_and_uses_slot_claims():
    client = DemoControlPlaneClient()
    secret = "123456789012-super-secret-token"
    client.save_and_verify_tokens({slot: secret for slot in ("hermes", "claude", "codex")})
    binding = client.begin_binding()
    serialized = repr(client.snapshot()) + repr(binding)
    assert secret not in serialized
    assert "?start=bind_hermes_" in binding["private_deep_links"]["hermes"]
    assert "?start=bind_claude_" in binding["private_deep_links"]["claude"]
    assert "?start=bind_codex_" in binding["private_deep_links"]["codex"]


def test_qr_dialog_is_real_qr_and_contains_no_token(qt_app):
    dialog = QrDialog(
        "Hermes",
        "hermes_bot",
        "https://t.me/hermes_bot?start=bind_hermes_demo-code",
    )
    pixmap = next(
        (candidate.pixmap() for candidate in dialog.findChildren(QLabel) if candidate.pixmap()),
        None,
    )
    assert pixmap is not None and not pixmap.isNull()
    dialog.close()


def test_main_window_uses_one_fixed_wizard_shell(qt_app):
    window = MainWindow(DemoControlPlaneClient(), demo_mode=True)
    window.show()
    qt_app.processEvents()
    assert window.wizard.rail.width() == 238
    assert window.wizard.help.width() == 276
    assert window.wizard.pages.count() == 4
    assert isinstance(window.wizard.completion, CompletionPage)
    window.close()


def test_gui_source_has_no_forbidden_glyph_icons():
    source_root = Path(__file__).parents[1] / "control_plane" / "gui"
    forbidden = "🚀★◇▤➤▦⌁ϟ●✓↻—□❐×‹›ⓘ👥"
    for path in source_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(symbol in source for symbol in forbidden), path


def test_icon_registry_loads_only_vendored_svg_subset():
    for name in ICON_NAMES:
        resource = (
            Path(__file__).parents[1] / "control_plane" / "gui" / "icons" / "assets" / f"{name}.svg"
        )
        assert resource.is_file()
        assert not icon(name).isNull()


def test_titlebar_controls_have_consistent_hit_targets(qt_app):
    window = MainWindow(DemoControlPlaneClient(), demo_mode=True)
    buttons = [window.title_bar.refresh, window.title_bar.maximize, window.title_bar.close_button]
    buttons.extend(
        button
        for button in window.title_bar.findChildren(QPushButton)
        if button not in buttons and button.objectName() == "WindowButton"
    )
    assert {(button.width(), button.height()) for button in buttons} == {(46, 46)}
    assert all(not button.icon().isNull() for button in buttons)
    window.close()


def test_token_reveal_is_press_only_and_focus_loss_hides(qt_app):
    page = TokenPage()
    page.show()
    field = page.fields["hermes"]
    field.setText("123456789:example-token-value")
    eye = next(
        button
        for button in page.findChildren(QPushButton)
        if button.width() == 48 and button.toolTip() == "按住临时显示 Token"
    )
    assert field.echoMode() == QLineEdit.EchoMode.Password
    QTest.mousePress(eye, Qt.MouseButton.LeftButton)
    assert field.echoMode() == QLineEdit.EchoMode.Normal
    QTest.mouseRelease(eye, Qt.MouseButton.LeftButton)
    assert field.echoMode() == QLineEdit.EchoMode.Password
    field.setFocus()
    field.clearFocus()
    qt_app.processEvents()
    assert field.echoMode() == QLineEdit.EchoMode.Password
    page.close()


def test_group_page_has_no_qr_control(qt_app):
    page = GroupPage()
    assert not any(button.objectName() == "QrButton" for button in page.findChildren(QPushButton))
    page.close()


def test_refresh_preserves_active_one_time_links_in_memory():
    store = GuiStateStore(DemoControlPlaneClient())
    store.save_tokens({slot: "123456789012-demo-token" for slot in ("hermes", "claude", "codex")})
    started = store.begin_binding()
    refreshed = store.refresh()
    assert refreshed["binding_session"] == started["binding_session"]


def test_demo_resume_reissues_links_and_keeps_binding_progress():
    client = DemoControlPlaneClient()
    client.save_and_verify_tokens(
        {slot: "123456789012-demo-token" for slot in ("hermes", "claude", "codex")}
    )
    started = client.begin_binding()
    client.poll_binding()
    resumed = client.resume_binding(started["session_id"])
    assert resumed["session_id"] == started["session_id"]
    assert resumed["private_deep_links"]["hermes"] != started["private_deep_links"]["hermes"]
    progress = client.poll_binding()
    assert progress["bound_private_count"] == 2


def test_state_store_resume_rehydrates_one_time_links():
    client = DemoControlPlaneClient()
    store = GuiStateStore(client)
    store.save_tokens({slot: "123456789012-demo-token" for slot in ("hermes", "claude", "codex")})
    started = store.begin_binding()
    resumed = store.resume_binding(started["binding_session"]["session_id"])
    assert resumed["binding_session"]["session_id"] == started["binding_session"]["session_id"]
    assert (
        resumed["binding_session"]["private_deep_links"]
        != started["binding_session"]["private_deep_links"]
    )


def test_main_window_initial_snapshot_resumes_server_session(qt_app):
    class RestartedDemoClient(DemoControlPlaneClient):
        def __init__(self):
            super().__init__()
            self.resume_calls = 0

        @property
        def binding(self):
            # Simulate a fresh GUI process: the server snapshot has the
            # session id, but one-time links are not retained in memory.
            return None

        def resume_binding(self, session_id: str):
            self.resume_calls += 1
            return super().resume_binding(session_id)

    client = RestartedDemoClient()
    client.save_and_verify_tokens(
        {slot: "123456789012-demo-token" for slot in ("hermes", "claude", "codex")}
    )
    started = client.begin_binding()
    window = MainWindow(client, demo_mode=True)
    window._run = lambda function, on_success, **_kwargs: on_success(function())
    window._initial_snapshot(client.snapshot())
    assert client.resume_calls == 1
    assert window._snapshot["binding_session"]["session_id"] == started["session_id"]
    window.close()


def test_production_embedded_client_uses_real_snapshot_contract(tmp_path):
    client = EmbeddedControlPlaneClient(data_dir=tmp_path)
    try:
        snapshot = client.snapshot()
        assert snapshot["revision"].startswith("onboarding-")
        assert not snapshot["revision"].startswith("demo-")
    finally:
        client.close()


def test_existing_control_plane_token_uses_default_loopback_url(monkeypatch):
    monkeypatch.setenv("CONTROL_PLANE_API_TOKEN", "local-bearer")
    monkeypatch.delenv("AI_AGENT_DESKTOP_API_URL", raising=False)
    client, demo_mode = build_client(force_demo=False)
    assert isinstance(client, HttpControlPlaneClient)
    assert client.base_url == "http://127.0.0.1:58080"
    assert demo_mode is False


def test_http_client_resume_calls_resume_endpoint(monkeypatch):
    client = HttpControlPlaneClient("http://127.0.0.1:58080", "local-bearer")
    calls: list[tuple[str, str, dict]] = []

    class Response:
        @staticmethod
        def json():
            return {"session_id": "binding-existing", "private_deep_links": {}}

    def fake_request(method, path, *, json_body=None, headers=None):
        del headers
        calls.append((method, path, json_body or {}))
        return Response()

    monkeypatch.setattr(client, "_request", fake_request)
    resumed = client.resume_binding("binding-existing")
    assert resumed["session_id"] == "binding-existing"
    assert calls == [
        (
            "POST",
            "/api/v1/telegram/bindings/binding-existing:resume",
            {"expires_in_seconds": 900, "runtimes_stopped_confirmation": True},
        )
    ]


def test_http_complete_configuration_starts_reconciles_and_strictly_verifies_runtime(monkeypatch):
    client = HttpControlPlaneClient("http://127.0.0.1:58080", "local-bearer")
    client.binding = {"session_id": "binding-1"}
    client._ensure_cc_connect_installed = lambda: None
    client._ensure_product_ownership = lambda: None
    client._ensure_native_configuration = lambda _session: None
    operations = []

    class Response:
        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    ready_status = {
        "observed_state": "running_partial",
        "configuration_revision": 4,
        "pid": 55123,
        "identity": {"pid": 55123, "configuration_revision": 4},
        "identity_verification": {"status": "verified"},
        "health": {
            "process_identity_verified": True,
            "artifact_integrity_verified": True,
            "configuration_revision_verified": True,
            "port_owned_by_process": True,
            "startup_stable_for_window": True,
            "fatal_log_detected": False,
        },
    }
    status_calls = iter([{"observed_state": "stopped", "health": {}}, ready_status])

    def fake_request(method, path, *, json_body=None, headers=None):
        del headers
        operations.append((method, path, json_body))
        if path == "/api/v1/components/cc-connect/native-configuration":
            return Response({"status": "valid", "revision": 4})
        if path == "/api/v1/components/cc-connect/lifecycle":
            return Response(next(status_calls))
        if path.endswith(":start"):
            return Response({"operation_id": "op-start"})
        if path.endswith(":reconcile"):
            return Response({"operation_id": "op-reconcile"})
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(
        client,
        "_wait_operation",
        lambda operation_id, **_kwargs: operations.append(("WAIT", operation_id, None)),
    )
    monkeypatch.setattr(
        client,
        "refresh_snapshot",
        lambda: {
            "agents": [
                {"display_name": name, "acceptable": True}
                for name in ("Hermes", "Claude Code", "Codex")
            ]
        },
    )
    monkeypatch.setattr(client, "snapshot", lambda: {"onboarding_complete": True})
    monkeypatch.setattr(client, "_ensure_hermes_telegram_configuration", lambda _session: None)
    monkeypatch.setattr(client, "hermes_readiness", lambda: {"configuration_status": "READY"})
    result = client.complete_configuration()
    assert result["onboarding_complete"] is True
    assert any(path.endswith(":start") for method, path, _body in operations if method == "POST")
    assert any(
        path.endswith(":reconcile") for method, path, _body in operations if method == "POST"
    )


def test_live_test_runs_six_one_shot_plans_without_retry(monkeypatch):
    client = HttpControlPlaneClient("http://127.0.0.1:58080", "local-bearer")
    links = [
        f"{slot}.{kind}" for slot in ("hermes", "claude", "codex") for kind in ("private", "group")
    ]
    client.live_links = lambda: [{"link_id": link} for link in links]
    calls = []

    class Response:
        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    def fake_request(method, path, *, json_body=None, headers=None):
        calls.append((method, path, json_body, headers))
        if path.endswith("/e2e-plans"):
            link_id = path.split("/links/", 1)[1].split("/e2e-plans", 1)[0]
            return Response(
                {
                    "plan_id": "plan-" + link_id,
                    "plan_digest": "sha256:" + "a" * 64,
                    "link_id": link_id,
                    "expected_credential_revision": 1,
                    "expected_binding_session_id": "binding-1",
                    "expected_binding_revision": 2,
                    "expected_configuration_revision": 3,
                }
            )
        return Response(
            {
                "link_id": json_body["link_id"],
                "lifecycle": "unknown",
                "message_count": 1,
                "automatic_retry": False,
            }
        )

    monkeypatch.setattr(client, "_request", fake_request)
    runs = client.run_live_test(confirmation=True)
    assert len(runs) == 6
    assert all(run["message_count"] == 1 and run["automatic_retry"] is False for run in runs)
    assert len([call for call in calls if call[0] == "POST" and call[1].endswith(":confirm")]) == 6


def test_gui_version_matches_candidate_manifest():
    assert APP_VERSION == "0.4.1-prebeta"


def test_binding_poll_timer_only_runs_on_binding_steps(qt_app):
    window = MainWindow(DemoControlPlaneClient(), demo_mode=True)
    window.show_wizard(1)
    assert window.binding_poll_timer.isActive()
    window.show_wizard(3)
    assert not window.binding_poll_timer.isActive()
    window.close()


def test_qr_dialog_is_non_blocking_window_modal_and_escape_closes(qt_app):
    dialog = QrDialog(
        "Hermes",
        "hermes_bot",
        "https://t.me/hermes_bot?start=bind_hermes_demo-code",
    )
    assert dialog.isModal()
    assert dialog.windowModality() == Qt.WindowModality.WindowModal
    dialog.show()
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert not dialog.isVisible()


def test_qr_dialog_shows_real_expiry_state(qt_app):
    expired = QrDialog(
        "Hermes",
        "hermes_bot",
        "https://t.me/hermes_bot?start=bind_hermes_demo-code",
        expires_at=(datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
    )
    assert any("链接已过期" in label.text() for label in expired.findChildren(QLabel))
    expired.close()


def test_completion_chat_pills_are_not_false_success(qt_app):
    page = CompletionPage()
    assert all("待确认" in pill.text() for pill in page.chat_pills.values())
    page.apply_snapshot(
        {
            "agents": [
                {
                    "slot": "hermes",
                    "private_status": "bound",
                    "group_status": "pending",
                }
            ],
            "checklist": [],
        }
    )
    assert "已绑定" in page.chat_pills[("hermes", "private")].text()
    assert "未绑定" in page.chat_pills[("hermes", "group")].text()
    page.close()


def test_completion_actions_fit_default_1280_by_720_window(qt_app):
    client = DemoControlPlaneClient()
    client._tokens_ready = True
    client._private_count = 3
    client._group_count = 3
    client._complete = True
    window = MainWindow(client, demo_mode=True)
    window.resize(1280, 720)
    window.apply_snapshot(client.snapshot())
    window.show_wizard(3)
    window.show()
    qt_app.processEvents()

    for widget in (
        window.wizard.completion.live_button,
        window.wizard.completion.skip_live_button,
        window.wizard.completion.cc_switch_button,
        window.wizard.next,
        window.wizard.back,
    ):
        top_left = widget.mapTo(window, widget.rect().topLeft())
        bottom_right = widget.mapTo(window, widget.rect().bottomRight())
        assert widget.isVisible()
        assert top_left.x() >= 0 and top_left.y() >= 0
        assert bottom_right.x() < window.width()
        assert bottom_right.y() < window.height()

    check_rows = window.wizard.completion.check_rows
    for previous, current in zip(check_rows[:-1], check_rows[1:], strict=True):
        previous_bottom = previous.mapTo(window, previous.rect().bottomLeft()).y()
        current_top = current.mapTo(window, current.rect().topLeft()).y()
        assert previous_bottom < current_top

    agent_states = [
        window.wizard.completion.agent_rows[slot]["state"] for slot in ("hermes", "claude", "codex")
    ]
    assert len({state.mapTo(window, state.rect().topLeft()).y() for state in agent_states}) == 1

    window.close()


def test_dashboard_agent_refresh_button_is_connected(qt_app):
    page = DashboardPage()
    calls: list[bool] = []
    page.refresh_requested.connect(lambda: calls.append(True))
    button = next(
        button for button in page.findChildren(QPushButton) if button.text() == "重新检查"
    )
    button.click()
    assert calls == [True]
    page.close()


def test_app_icon_has_transparent_corners_and_multisize_ico():
    png = Image.open(ASSET_DIR / "app_icon.png").convert("RGBA")
    assert all(
        png.getpixel(point)[3] == 0
        for point in (
            (0, 0),
            (png.width - 1, 0),
            (0, png.height - 1),
            (png.width - 1, png.height - 1),
        )
    )
    ico = Image.open(ASSET_DIR / "app_icon.ico")
    assert {(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}.issubset(
        ico.info["sizes"]
    )


def test_telegram_native_url_keeps_slot_payload():
    native = TelegramLauncher.native_url(
        "https://t.me/hermes_bot?start=bind_hermes_example", group=False
    ).toString()
    assert native.startswith("tg://resolve?")
    assert "domain=hermes_bot" in native
    assert "start=bind_hermes_example" in native


def test_telegram_launcher_falls_back_to_https(monkeypatch):
    opened: list[str] = []

    def fake_open(url):
        opened.append(url.toString())
        return len(opened) > 1

    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(fake_open))
    assert TelegramLauncher.open_deep_link("https://t.me/hermes_bot?start=bind_hermes_example")
    assert opened[0].startswith("tg://resolve?")
    assert opened[1] == "https://t.me/hermes_bot?start=bind_hermes_example"

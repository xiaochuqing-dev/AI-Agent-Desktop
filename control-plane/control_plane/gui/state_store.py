from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from .api_client import GuiApiClient, GuiApiError


class GuiStateStore:
    """Observable GUI state whose source of truth is always the API client."""

    def __init__(self, client: GuiApiClient) -> None:
        self.client = client
        self._snapshot: dict[str, Any] = {}
        self._listeners: list[Callable[[dict[str, Any]], None]] = []

    @property
    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self._snapshot)

    def subscribe(self, listener: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.append(listener)

    def _publish(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        self._snapshot = deepcopy(snapshot)
        for listener in tuple(self._listeners):
            listener(deepcopy(self._snapshot))
        return self.snapshot

    def refresh(self) -> dict[str, Any]:
        refresh_reader = getattr(self.client, "refresh_snapshot", None)
        snapshot = refresh_reader() if callable(refresh_reader) else self.client.snapshot()
        dashboard_reader = getattr(self.client, "dashboard_snapshot", None)
        if callable(dashboard_reader):
            try:
                snapshot["dashboard"] = dashboard_reader()
            except GuiApiError:
                # The onboarding read model remains authoritative if an older
                # loopback service does not expose the dashboard endpoint yet.
                pass
        readiness_reader = getattr(self.client, "hermes_readiness", None)
        if callable(readiness_reader):
            try:
                binding_session_id = (getattr(self.client, "binding", None) or {}).get("session_id")
                if binding_session_id:
                    try:
                        snapshot["hermes_telegram"] = readiness_reader(
                            binding_session_id=binding_session_id
                        )
                    except TypeError:
                        # Demo and legacy loopback clients keep the older no-arg read model.
                        snapshot["hermes_telegram"] = readiness_reader()
                else:
                    snapshot["hermes_telegram"] = readiness_reader()
            except GuiApiError as exc:
                snapshot["hermes_telegram"] = {
                    "configuration_status": "UNKNOWN",
                    "diagnostic_code": exc.code,
                    "user_message": str(exc),
                }
        # A refresh is read-only, but an active binding session's one-time
        # links are still needed by the current window.  Keep the in-memory
        # display-only copy; the Control Plane remains the source of truth.
        binding = getattr(self.client, "binding", None)
        if binding:
            snapshot["binding_session"] = deepcopy(binding)
        try:
            diagnostics = self.client.diagnostics()
            hermes = snapshot.get("hermes_telegram") or {}
            if hermes.get("diagnostic_code") and hermes.get("configuration_status") != "SAME_BOT":
                diagnostics.append(
                    {
                        "code": hermes.get("diagnostic_code"),
                        "severity": "warning",
                        "user_message": hermes.get("user_message") or "Hermes Telegram 需要处理。",
                        "suggested_actions": ["inspect_hermes_telegram_readiness"],
                    }
                )
            snapshot["diagnostics"] = diagnostics
            dashboard = snapshot.get("dashboard")
            if isinstance(dashboard, dict):
                issues = list(dashboard.get("recent_issues") or [])
                issues.extend(
                    item.get("user_message") or item.get("summary") or "需要进一步检查。"
                    for item in diagnostics
                )
                dashboard["recent_issues"] = list(dict.fromkeys(issues))
        except GuiApiError:
            pass
        return self._publish(snapshot)

    def save_tokens(self, values: dict[str, str]) -> dict[str, Any]:
        return self._publish(self.client.save_and_verify_tokens(values))

    def begin_binding(self) -> dict[str, Any]:
        binding = self.client.begin_binding()
        snapshot = self.client.snapshot()
        snapshot["binding_session"] = binding
        return self._publish(snapshot)

    def resume_binding(self, session_id: str) -> dict[str, Any]:
        binding = self.client.resume_binding(session_id)
        snapshot = self.client.snapshot()
        snapshot["binding_session"] = binding
        return self._publish(snapshot)

    def poll_binding(self) -> dict[str, Any]:
        binding = self.client.poll_binding()
        snapshot = self.client.snapshot()
        snapshot["binding_session"] = binding
        return self._publish(snapshot)

    def complete_configuration(self) -> dict[str, Any]:
        return self._publish(self.client.complete_configuration())

    def run_live_test(self, *, confirmation: bool) -> dict[str, Any]:
        runs = self.client.run_live_test(confirmation=confirmation)
        snapshot = self.client.snapshot()
        snapshot["live_test_runs"] = runs
        dashboard_reader = getattr(self.client, "dashboard_snapshot", None)
        if callable(dashboard_reader):
            snapshot["dashboard"] = dashboard_reader()
        return self._publish(snapshot)

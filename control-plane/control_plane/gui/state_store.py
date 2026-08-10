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
        snapshot = self.client.snapshot()
        dashboard_reader = getattr(self.client, "dashboard_snapshot", None)
        if callable(dashboard_reader):
            try:
                snapshot["dashboard"] = dashboard_reader()
            except GuiApiError:
                # The onboarding read model remains authoritative if an older
                # loopback service does not expose the dashboard endpoint yet.
                pass
        # A refresh is read-only, but an active binding session's one-time
        # links are still needed by the current window.  Keep the in-memory
        # display-only copy; the Control Plane remains the source of truth.
        binding = getattr(self.client, "binding", None)
        if binding:
            snapshot["binding_session"] = deepcopy(binding)
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

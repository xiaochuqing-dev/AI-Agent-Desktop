from __future__ import annotations

import socket
from collections.abc import Callable, Iterable
from typing import Any, Literal

import psutil

from ..installer.artifacts import InstallerError
from .models import PortOwnershipEvidence

CONTROLLED_PORT_START = 59000
CONTROLLED_PORT_END = 59999
RESERVED_PORTS = frozenset({58080, 8423, 9810, 9820})


class PortOwnershipInspector:
    def __init__(
        self,
        *,
        connections_provider: Callable[[], Iterable[Any]] | None = None,
    ) -> None:
        self._connections_provider = connections_provider or (
            lambda: psutil.net_connections(kind="tcp4")
        )

    def choose_available(self) -> int:
        for port in range(CONTROLLED_PORT_START, CONTROLLED_PORT_END + 1):
            if port not in RESERVED_PORTS and self.is_available("127.0.0.1", port):
                return port
        raise InstallerError(
            "MANAGED_PORT_RANGE_EXHAUSTED",
            "No free loopback port remains in the product-controlled range.",
            retryable=True,
            recovery_actions=["close_unused_product_instances", "retry_configuration_plan"],
        )

    def validate_controlled_port(self, host: str, port: int) -> None:
        if host != "127.0.0.1":
            raise InstallerError(
                "NON_LOOPBACK_LISTEN_FORBIDDEN",
                "Product-managed cc-connect may listen only on 127.0.0.1.",
                recovery_actions=["create_new_configuration_plan"],
            )
        if not CONTROLLED_PORT_START <= port <= CONTROLLED_PORT_END or port in RESERVED_PORTS:
            raise InstallerError(
                "MANAGED_PORT_OUTSIDE_CONTROLLED_RANGE",
                "Requested port is outside the product-controlled range.",
                recovery_actions=["create_new_configuration_plan"],
            )

    def is_available(self, host: str, port: int) -> bool:
        self.validate_controlled_port(host, port)
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            if exclusive is not None:
                probe.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            probe.bind((host, port))
            return True
        except OSError:
            return False
        finally:
            probe.close()

    def inspect(
        self, host: str, port: int, expected_pid: int | None = None
    ) -> PortOwnershipEvidence:
        self.validate_controlled_port(host, port)
        try:
            connections = list(self._connections_provider())
        except (OSError, psutil.Error):
            return PortOwnershipEvidence(
                listen_port=port,
                status="unknown",
                expected_pid=expected_pid,
                evidence={"reason": "CONNECTION_TABLE_INACCESSIBLE"},
            )
        owner_pids: set[int] = set()
        for connection in connections:
            status = str(getattr(connection, "status", "")).upper()
            local = getattr(connection, "laddr", None)
            if status != "LISTEN" or not local:
                continue
            local_host, local_port = self._address(local)
            if local_port != port or local_host not in {host, "0.0.0.0"}:
                continue
            pid = getattr(connection, "pid", None)
            if isinstance(pid, int):
                owner_pids.add(pid)
        if not owner_pids:
            status_value: Literal["free", "unknown"] = (
                "free" if self.is_available(host, port) else "unknown"
            )
            return PortOwnershipEvidence(
                listen_port=port,
                status=status_value,
                expected_pid=expected_pid,
                evidence={
                    "owner_pids": [],
                    "reason": (
                        "PORT_FREE" if status_value == "free" else "PORT_BUSY_OWNER_NOT_VISIBLE"
                    ),
                },
            )
        if expected_pid is not None and owner_pids == {expected_pid}:
            return PortOwnershipEvidence(
                listen_port=port,
                status="owned",
                owner_pid=expected_pid,
                expected_pid=expected_pid,
                evidence={"owner_pids": sorted(owner_pids)},
            )
        return PortOwnershipEvidence(
            listen_port=port,
            status="conflict",
            owner_pid=next(iter(owner_pids)) if len(owner_pids) == 1 else None,
            expected_pid=expected_pid,
            evidence={"owner_pids": sorted(owner_pids)},
        )

    @staticmethod
    def _address(address: Any) -> tuple[str, int]:
        if hasattr(address, "ip") and hasattr(address, "port"):
            return str(address.ip), int(address.port)
        return str(address[0]), int(address[1])

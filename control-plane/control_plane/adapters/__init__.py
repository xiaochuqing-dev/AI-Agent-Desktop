# Adapter 注册表。装载内置只读 Adapter,做超时、取消与故障隔离(首片同进程)。
from __future__ import annotations

from typing import Optional

from ..domain.ports import DiscoveryAdapter


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: list[DiscoveryAdapter] = []

    def register(self, adapter: DiscoveryAdapter) -> None:
        self._adapters.append(adapter)

    def all(self) -> list[DiscoveryAdapter]:
        return list(self._adapters)

    def find(self, adapter_id: str) -> Optional[DiscoveryAdapter]:
        for a in self._adapters:
            if a.adapter_id == adapter_id:
                return a
        return None

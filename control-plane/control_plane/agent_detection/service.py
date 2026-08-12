from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import cast

from .detectors import AgentDetector, ClaudeCodeDetector, CodexDetector, HermesDetector
from .models import AgentDetectionResult, AgentDetectionSnapshot, AgentId

SLOTS: tuple[AgentId, ...] = ("hermes", "claude", "codex")


class AgentDetectionService:
    def __init__(
        self,
        detectors: dict[AgentId, AgentDetector] | None = None,
        *,
        ttl_seconds: float = 30.0,
        monotonic=time.monotonic,
    ) -> None:
        self.detectors = detectors or {
            "hermes": HermesDetector(),
            "claude": ClaudeCodeDetector(),
            "codex": CodexDetector(),
        }
        self.ttl_seconds = ttl_seconds
        self.monotonic = monotonic
        self._cache: dict[AgentId, tuple[float, AgentDetectionResult]] = {}
        self._lock = threading.RLock()

    def refresh(self) -> dict[AgentId, AgentDetectionResult]:
        results: dict[AgentId, AgentDetectionResult] = {}
        with ThreadPoolExecutor(max_workers=len(SLOTS), thread_name_prefix="agent-detect") as pool:
            futures = {pool.submit(self.detectors[slot].detect): slot for slot in SLOTS}
            for future in as_completed(futures):
                slot = futures[future]
                results[slot] = future.result()
        cached_at = self.monotonic()
        with self._lock:
            for slot in SLOTS:
                self._cache[slot] = (cached_at, results[slot])
        return {slot: results[slot] for slot in SLOTS}

    def get_all(self, *, refresh: bool = False) -> dict[AgentId, AgentDetectionResult]:
        now = self.monotonic()
        with self._lock:
            fresh = len(self._cache) == len(SLOTS) and all(
                now - cached_at <= self.ttl_seconds for cached_at, _result in self._cache.values()
            )
            if fresh and not refresh:
                return {slot: self._cache[slot][1] for slot in SLOTS}
        return self.refresh()

    def get(self, slot: AgentId, *, refresh: bool = False) -> AgentDetectionResult:
        return self.get_all(refresh=refresh)[slot]

    def public_snapshots(self, *, refresh: bool = False) -> list[AgentDetectionSnapshot]:
        results = self.get_all(refresh=refresh)
        return [results[cast(AgentId, slot)].public_snapshot() for slot in SLOTS]

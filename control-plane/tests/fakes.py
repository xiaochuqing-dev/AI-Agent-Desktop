# 合成 Fake Adapter,供 API 与发现服务测试使用。绝不扫描真实运行环境。
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from control_plane.agent_detection.models import (
    AgentDetectionResult,
    DetectionSource,
    DetectionStatus,
    ProbeStatus,
)
from control_plane.agent_detection.service import AgentDetectionService
from control_plane.domain.models import (
    AuthenticationState,
    Capability,
    CapabilityAvailability,
    CapabilityMaturity,
    Component,
    ConfigurationState,
    HealthState,
    InstallationState,
    RuntimeState,
    StateSnapshot,
    UpdateState,
    UserStatus,
)
from control_plane.domain.ports import DiscoveryAdapter


def _ts() -> datetime:
    return datetime.now(UTC)


def _snap(
    installation: InstallationState,
    *,
    configuration: ConfigurationState = ConfigurationState.VALID,
    runtime: RuntimeState = RuntimeState.RUNNING,
    health: HealthState = HealthState.HEALTHY,
    user_status: UserStatus = UserStatus.RUNNING_HEALTHY,
) -> StateSnapshot:
    return StateSnapshot(
        installation=installation,
        configuration=configuration,
        authentication=AuthenticationState.NOT_REQUIRED,
        runtime=runtime,
        health=health,
        update=UpdateState.UP_TO_DATE,
        user_status=user_status,
        status_overlays=[],
        conditions=[],
        generation=1,
        observed_generation=1,
        revision="fake-r1",
        observed_at=_ts(),
    )


class FakeHealthyAdapter(DiscoveryAdapter):
    adapter_id = "fake-healthy"
    component_kinds = ["agent"]

    def discover(self) -> list[Component]:
        return [
            Component(
                component_id="fake-healthy",
                kind="agent",
                display_name="Fake Healthy",
                version="1.0.0",
                state=_snap(InstallationState.INSTALLED),
                provider_refs=[],
            )
        ]

    def capabilities(self) -> list[Capability]:
        return [
            Capability(
                capability_id="lifecycle.discover.v1",
                version="1.0.0",
                maturity=CapabilityMaturity.STABLE,
                availability=CapabilityAvailability.AVAILABLE,
                constraints={},
            )
        ]


class FakeMissingAdapter(DiscoveryAdapter):
    adapter_id = "fake-missing"
    component_kinds = ["agent"]

    def discover(self) -> list[Component]:
        return [
            Component(
                component_id="fake-missing",
                kind="agent",
                display_name="Fake Missing",
                version=None,
                state=_snap(
                    InstallationState.NOT_INSTALLED,
                    configuration=ConfigurationState.MISSING,
                    runtime=RuntimeState.UNKNOWN,
                    health=HealthState.UNKNOWN,
                    user_status=UserStatus.NOT_INSTALLED,
                ),
                provider_refs=[],
            )
        ]

    def capabilities(self) -> list[Capability]:
        return []


class FakeUnknownAdapter(DiscoveryAdapter):
    adapter_id = "fake-unknown"
    component_kinds = ["agent"]

    def discover(self) -> list[Component]:
        return [
            Component(
                component_id="fake-unknown",
                kind="agent",
                display_name="Fake Unknown",
                version=None,
                state=_snap(
                    InstallationState.INSTALLED,
                    configuration=ConfigurationState.UNKNOWN,
                    runtime=RuntimeState.UNKNOWN,
                    health=HealthState.UNKNOWN,
                    user_status=UserStatus.UNKNOWN,
                ),
                provider_refs=[],
            )
        ]

    def capabilities(self) -> list[Capability]:
        return []


class FakeFailingAdapter(DiscoveryAdapter):
    adapter_id = "fake-failing"
    component_kinds = ["agent"]

    def discover(self) -> list[Component]:
        raise RuntimeError("private-path\\must-not-leak")

    def capabilities(self) -> list[Capability]:
        return []


def make_fake_adapters() -> list[DiscoveryAdapter]:
    return [FakeHealthyAdapter(), FakeMissingAdapter()]


class FakeAgentDetector:
    def __init__(self, slot: str, display_name: str, *, installed: bool = True) -> None:
        self.agent_id = slot
        self.display_name = display_name
        self.installed = installed

    def detect(self) -> AgentDetectionResult:
        return AgentDetectionResult(
            agent_id=self.agent_id,  # type: ignore[arg-type]
            display_name=self.display_name,
            status=DetectionStatus.INSTALLED if self.installed else DetectionStatus.NOT_FOUND,
            installed=self.installed,
            version="1.2.3" if self.installed else None,
            executable_path_internal=(
                str(Path("C:/synthetic") / f"{self.agent_id}.exe") if self.installed else None
            ),
            detection_source=(
                DetectionSource.KNOWN_LOCATION if self.installed else DetectionSource.NOT_FOUND
            ),
            probe_status=ProbeStatus.HEALTHY if self.installed else ProbeStatus.NOT_RUN,
            observed_at=_ts(),
            diagnostic_code=None if self.installed else "AGENT_NOT_FOUND",
            user_message=(
                f"已检测到 {self.display_name}，版本 1.2.3。"
                if self.installed
                else f"没有检测到 {self.display_name}。"
            ),
            official_install_url=f"https://example.invalid/{self.agent_id}",
            revision=f"sha256:{self.agent_id:0<64}",
        )


def make_fake_agent_detection(*, installed: bool = True) -> AgentDetectionService:
    return AgentDetectionService(
        {
            "hermes": FakeAgentDetector("hermes", "Hermes", installed=installed),
            "claude": FakeAgentDetector("claude", "Claude Code", installed=installed),
            "codex": FakeAgentDetector("codex", "Codex", installed=installed),
        },  # type: ignore[arg-type]
        ttl_seconds=3600,
    )

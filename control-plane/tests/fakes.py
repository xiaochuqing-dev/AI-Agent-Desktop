# 合成 Fake Adapter,供 API 与发现服务测试使用。绝不扫描真实运行环境。
from __future__ import annotations

from datetime import datetime, timezone

from control_plane.domain.models import (
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
    return datetime.now(timezone.utc)


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
        authentication="not_required",
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


def make_fake_adapters() -> list[DiscoveryAdapter]:
    return [FakeHealthyAdapter(), FakeMissingAdapter()]

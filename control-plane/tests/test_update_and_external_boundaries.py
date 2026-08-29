from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from control_plane.configuration.migrations import ConfigurationMigrationRegistry
from control_plane.external_tools.cc_switch import CcSwitchExternalToolProvider
from control_plane.installer.artifacts import load_artifact_lock
from control_plane.persistence.models import ComponentVersionRecord, ExternalToolCapabilityRecord
from control_plane.updates.models import (
    AvailableVersion,
    UpdateChannel,
    VersionPolicy,
)
from control_plane.updates.providers import CcConnectArtifactProvider, HermesUpdateProvider

from .test_installer_service import _add_previous_version


def exact_policy(version: str) -> VersionPolicy:
    return VersionPolicy(channel=UpdateChannel.EXACT, requested_version=version)


def test_cc_connect_assessment_comes_from_lock_and_supports_multi_version_store(
    managed_runtime_environment,
):
    environment = managed_runtime_environment
    provider = CcConnectArtifactProvider(environment["database"], environment["version_store"])
    lock = load_artifact_lock()
    assessment = provider.assess(exact_policy(lock["version"]))
    assert assessment.status == "already_current"
    assert assessment.target_version is not None
    assert assessment.target_version.artifact_id == lock["artifact_id"]
    assert assessment.target_version.source_kind == "artifact_lock"
    assert assessment.automatic_update_performed is False
    assert assessment.upstream_patch_modified is False

    with environment["database"].session() as session:
        session.add(
            ComponentVersionRecord(
                artifact_id="cc-connect-previous-test-version",
                component_id="cc-connect",
                version="v0.0-test",
                relative_path="versions/cc-connect-previous-test-version",
                artifact_sha256="a" * 64,
                artifact_size=1,
                status="installed",
                installed_at=datetime.now(UTC),
                removed_at=None,
            )
        )
    versions = provider.installed_versions()
    assert len(versions) == 2
    assert sum(item.current for item in versions) == 1


def test_unlocked_target_and_latest_policy_are_never_assumed(managed_runtime_environment):
    environment = managed_runtime_environment
    provider = CcConnectArtifactProvider(environment["database"], environment["version_store"])
    unsupported = provider.assess(exact_policy("latest"))
    assert unsupported.status == "unsupported"
    assert unsupported.target_version is None
    with pytest.raises(ValidationError):
        VersionPolicy(
            channel=UpdateChannel.EXACT,
            requested_version="latest",
            use_latest=True,  # type: ignore[arg-type]
        )


def test_locked_upgrade_requires_native_configuration_revision_refresh(
    managed_runtime_environment,
):
    environment = managed_runtime_environment
    previous = _add_previous_version(
        environment["installer"], environment["database"], environment["manifest"]
    )
    current = environment["installer"].layout.read_current()
    assert current is not None
    current.update(
        {
            "artifact_id": previous.artifact_id,
            "version": previous.version,
            "artifact_sha256": previous.artifact_sha256,
            "previous_artifact_id": None,
            "revision": "update-assessment-previous",
        }
    )
    environment["installer"].layout.write_current(current)

    lock = load_artifact_lock()
    assessment = CcConnectArtifactProvider(
        environment["database"], environment["version_store"]
    ).assess(exact_policy(lock["version"]))

    assert assessment.status == "compatible"
    assert assessment.migration.required is True
    assert assessment.migration.status == "planned"
    assert assessment.migration.entrypoint == "cc_connect.native_configuration.create_plan"
    assert assessment.rollback_version.artifact_id == previous.artifact_id


def test_hermes_boundary_is_explicitly_unsupported_not_success():
    assessment = HermesUpdateProvider().assess(exact_policy("1.0.0"))
    assert assessment.status == "unsupported"
    assert assessment.target_version is None
    assert assessment.migration.status == "unsupported"
    assert assessment.automatic_update_performed is False


def test_fake_update_source_can_be_injected_without_generic_updater():
    class FakeUpdateSource:
        source_id = "fake"

        def resolve(self, component_id: str, policy: VersionPolicy):
            return AvailableVersion(
                component_id=component_id,
                artifact_id="fake-artifact",
                version=policy.requested_version,
                artifact_sha256="b" * 64,
                channel=UpdateChannel.EXACT,
                source_kind="artifact_lock",
            )

    resolved = FakeUpdateSource().resolve("cc-connect", exact_policy("v-test"))
    assert resolved.version == "v-test"
    assert resolved.artifact_id == "fake-artifact"


def test_cc_switch_absent_capabilities_remain_unknown(managed_runtime_environment, tmp_path):
    provider = CcSwitchExternalToolProvider(
        managed_runtime_environment["database"],
        candidates=[tmp_path / "missing-CCSwitch.exe"],
    )
    status = provider.detect()
    assert status.installation_status == "not_installed"
    capabilities = {item.capability: item.status for item in status.capabilities}
    assert capabilities["detection"] == "supported"
    assert capabilities["launch"] == "unavailable"
    assert capabilities["install"] == "unknown"
    assert capabilities["update"] == "unknown"
    assert capabilities["configuration"] == "unknown"
    assert status.supported_agents == []
    assert status.evidence["private_configuration_read"] is False
    with managed_runtime_environment["database"].session() as session:
        persisted = session.get(ExternalToolCapabilityRecord, provider.provider_id)
    assert persisted is not None and persisted.status == "not_installed"


def test_cc_switch_detect_and_normal_launch_do_not_automate_or_write(
    managed_runtime_environment, tmp_path
):
    executable = tmp_path / "CC Switch 中文 (test).exe"
    executable.write_bytes(b"test executable marker")
    calls: list[tuple[list[str], dict]] = []

    def launcher(arguments, **kwargs):
        calls.append((list(arguments), kwargs))
        return SimpleNamespace(pid=55123)

    provider = CcSwitchExternalToolProvider(
        managed_runtime_environment["database"],
        launcher=launcher,
        candidates=[executable],
    )
    status = provider.detect()
    assert status.installation_status == "installed"
    launched = provider.launch()
    assert launched == {
        "provider_id": "cc-switch-external",
        "launched": True,
        "pid": 55123,
        "configuration_written": False,
        "gui_automation_used": False,
    }
    assert calls[0][0] == [str(executable.resolve())]
    assert calls[0][1]["shell"] is False


def test_configuration_migration_registry_is_explicit_and_fails_closed():
    registry = ConfigurationMigrationRegistry()
    assert registry.assess("1.0", "1.0") == "not_required"
    assert registry.assess("1.0", "2.0") == "unsupported"
    with pytest.raises(ValueError, match="unsupported configuration migration"):
        registry.migrate({}, from_version="1.0", to_version="2.0")

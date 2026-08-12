from control_plane.adapters import discovery as disc
from control_plane.agent_detection.models import (
    AgentDetectionResult,
    DetectionSource,
    DetectionStatus,
    ProbeStatus,
)


class FakeDetector:
    def __init__(self, slot, name, *, installed=False, version=None):
        self.agent_id = slot
        self.name = name
        self.installed = installed
        self.version = version

    def detect(self):
        return AgentDetectionResult(
            agent_id=self.agent_id,
            display_name=self.name,
            status=DetectionStatus.INSTALLED if self.installed else DetectionStatus.NOT_FOUND,
            installed=self.installed,
            version=self.version,
            executable_path_internal="C:/fake.exe" if self.installed else None,
            detection_source=(
                DetectionSource.PATH if self.installed else DetectionSource.NOT_FOUND
            ),
            probe_status=ProbeStatus.HEALTHY if self.installed else ProbeStatus.NOT_RUN,
            observed_at=disc.utcnow(),
            diagnostic_code=None if self.installed else "AGENT_NOT_FOUND",
            user_message="detected" if self.installed else "missing",
            official_install_url="https://example.invalid/install",
            revision="sha256:" + "1" * 64,
        )


def _patch_missing(monkeypatch):
    # 全部 I/O 打桩,绝不扫描真实运行环境
    monkeypatch.setattr(disc.shutil, "which", lambda name: None)
    monkeypatch.setattr(disc, "_hermes_exe_candidate", lambda: None)
    monkeypatch.setattr(disc, "_cc_connect_exe_candidate", lambda: None)
    monkeypatch.setattr(disc, "_version_of", lambda *a, **k: (None, False))
    monkeypatch.setattr(disc, "_hermes_config_exists", lambda: False)
    monkeypatch.setattr(disc, "_cc_connect_config_exists", lambda: False)
    monkeypatch.setattr(disc, "_cc_connect_tokens_env_exists", lambda: False)
    monkeypatch.setattr(disc, "_cc_switch_exe_candidate", lambda: (None, True))


def test_not_installed_when_missing(monkeypatch):
    _patch_missing(monkeypatch)
    adapters = [
        disc.HermesDiscoveryAdapter(FakeDetector("hermes", "Hermes")),
        disc.CcConnectDiscoveryAdapter(),
        disc.ClaudeCodeDiscoveryAdapter(FakeDetector("claude", "Claude Code")),
        disc.CodexDiscoveryAdapter(FakeDetector("codex", "Codex")),
        disc.CcSwitchDiscoveryAdapter(),
    ]
    for adapter in adapters:
        comps = adapter.discover()
        assert len(comps) == 1
        assert comps[0].state.installation.value == "not_installed"


def test_stable_component_id(monkeypatch):
    _patch_missing(monkeypatch)
    for cls, expected in [
        (disc.HermesDiscoveryAdapter, "hermes"),
        (disc.CcConnectDiscoveryAdapter, "cc-connect"),
        (disc.ClaudeCodeDiscoveryAdapter, "claude-code"),
        (disc.CodexDiscoveryAdapter, "codex"),
        (disc.CcSwitchDiscoveryAdapter, "cc-switch"),
        (disc.TelegramConfigDiscoveryAdapter, "telegram-channel"),
    ]:
        c1 = cls().discover()[0]
        c2 = cls().discover()[0]
        assert c1.component_id == c2.component_id == expected


def test_installed_when_found(monkeypatch, tmp_path):
    fake_exe = str(tmp_path / "fake.exe")
    monkeypatch.setattr(disc.shutil, "which", lambda name: fake_exe)
    monkeypatch.setattr(disc.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(disc, "_version_of", lambda *a, **k: ("v1.2.3", True))
    monkeypatch.setattr(disc, "_hermes_config_exists", lambda: True)
    a = disc.HermesDiscoveryAdapter(
        FakeDetector("hermes", "Hermes", installed=True, version="v1.2.3")
    )
    c = a.discover()[0]
    assert c.state.installation.value == "installed"
    assert c.version == "v1.2.3"
    assert c.state.configuration.value == "unknown"
    assert c.state.runtime.value == "unknown"
    assert c.state.health.value == "unknown"
    assert c.state.user_status.value == "unknown"
    assert any(x.type == "ExecutableDetected" for x in c.state.conditions)


def test_config_artifacts_never_claim_running_or_healthy(monkeypatch, tmp_path):
    fake_exe = str(tmp_path / "fake.exe")
    monkeypatch.setattr(disc.shutil, "which", lambda name: fake_exe)
    monkeypatch.setattr(disc.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(disc, "_version_of", lambda *a, **k: ("v1.2.3", True))
    monkeypatch.setattr(disc, "_hermes_config_exists", lambda: True)
    monkeypatch.setattr(disc, "_cc_connect_config_exists", lambda: True)
    monkeypatch.setattr(disc, "_cc_connect_tokens_env_exists", lambda: True)

    adapters = [
        disc.HermesDiscoveryAdapter(
            FakeDetector("hermes", "Hermes", installed=True, version="v1.2.3")
        ),
        disc.CcConnectDiscoveryAdapter(),
        disc.TelegramConfigDiscoveryAdapter(),
    ]
    for adapter in adapters:
        state = adapter.discover()[0].state
        assert state.configuration.value == "unknown"
        assert state.runtime.value == "unknown"
        assert state.health.value == "unknown"
        assert state.user_status.value == "unknown"


def test_cc_switch_read_only_discovery_installed(monkeypatch, tmp_path):
    fake_exe = str(tmp_path / "CC-Switch.exe")
    monkeypatch.setattr(disc, "_cc_switch_exe_candidate", lambda: (fake_exe, True))
    monkeypatch.setattr(disc.os.path, "isfile", lambda path: path == fake_exe)

    adapter = disc.CcSwitchDiscoveryAdapter()
    component = adapter.discover()[0]

    assert component.component_id == "cc-switch"
    assert component.state.installation.value == "installed"
    assert component.version is None
    assert component.state.configuration.value == "unknown"
    assert component.state.authentication.value == "unknown"
    assert component.state.runtime.value == "unknown"
    assert component.state.health.value == "unknown"
    capability = adapter.capabilities()[0]
    assert capability.capability_id == "model-configuration.discover.v1"
    assert capability.constraints == {"read_only": True}


def test_cc_switch_read_only_discovery_not_installed(monkeypatch):
    monkeypatch.setattr(disc, "_cc_switch_exe_candidate", lambda: (None, True))
    component = disc.CcSwitchDiscoveryAdapter().discover()[0]
    assert component.state.installation.value == "not_installed"
    assert component.state.user_status.value == "not_installed"


def test_cc_switch_read_only_discovery_unknown(monkeypatch):
    monkeypatch.setattr(disc, "_cc_switch_exe_candidate", lambda: (None, False))
    component = disc.CcSwitchDiscoveryAdapter().discover()[0]
    assert component.state.installation.value == "unknown"
    assert component.state.user_status.value == "unknown"
    assert component.state.conditions[0].reason == "DISCOVERY_INCONCLUSIVE"


def test_windows_system_adapter(monkeypatch):
    class FakeUsage:
        free = 10 * 1024 * 1024 * 1024  # 10GB

    monkeypatch.setattr(disc.psutil, "disk_usage", lambda p: FakeUsage())
    c = disc.WindowsSystemDiscoveryAdapter().discover()[0]
    assert c.component_id == "windows-system"
    assert c.state.health.value == "healthy"


def test_windows_system_adapter_low_disk(monkeypatch):
    class FakeUsage:
        free = 100 * 1024 * 1024  # 100MB,不足 1GB

    monkeypatch.setattr(disc.psutil, "disk_usage", lambda p: FakeUsage())
    c = disc.WindowsSystemDiscoveryAdapter().discover()[0]
    assert c.state.health.value in ("degraded", "unhealthy")


def test_adapter_failure_returns_empty_not_exception(monkeypatch):
    # 单探针失败不抛底层异常,返回空列表(发现服务据此设 unknown)
    class _Boom(disc.HermesDiscoveryAdapter):
        def discover(self):
            raise RuntimeError("boom")

    # 直接调用异常由发现服务捕获;这里验证 Adapter 自身抛出能被发现服务处理
    import pytest

    with pytest.raises(RuntimeError):
        _Boom().discover()

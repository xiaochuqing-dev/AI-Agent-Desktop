from __future__ import annotations

from control_plane.cc_connect.external_detection import (
    CcConnectExternalDetector,
    ProcessObservation,
)
from control_plane.lifecycle.models import PortOwnershipEvidence


class StaticPortInspector:
    def __init__(self, owner_pid: int | None = None, *, unknown: bool = False) -> None:
        self.owner_pid = owner_pid
        self.unknown = unknown

    def inspect(self, host: str, port: int):
        assert host == "127.0.0.1"
        if self.unknown:
            return PortOwnershipEvidence(listen_port=port, status="unknown")
        if self.owner_pid is None:
            return PortOwnershipEvidence(listen_port=port, status="free")
        return PortOwnershipEvidence(
            listen_port=port,
            status="conflict",
            owner_pid=self.owner_pid,
            evidence={"owner_pids": [self.owner_pid]},
        )


def test_path_installation_alone_does_not_block(tmp_path):
    product = tmp_path / "product"
    external = tmp_path / "external" / "cc-connect.exe"
    detector = CcConnectExternalDetector(
        product,
        process_provider=lambda: [],
        port_inspector=StaticPortInspector(),  # type: ignore[arg-type]
        path_lookup=lambda _name: str(external),
        supervisor_probe=lambda: False,
    )
    state = detector.detect(target_port=59020)
    assert state.external_installed is True
    assert state.external_process_running is False
    assert state.conflict is False
    assert state.evidence["path_installation_alone_blocks"] is False


def test_external_process_different_port_is_evidence_but_not_conflict(tmp_path):
    external = tmp_path / "external" / "cc-connect.exe"
    detector = CcConnectExternalDetector(
        tmp_path / "product",
        process_provider=lambda: [
            ProcessObservation(
                pid=501,
                executable=str(external),
                command_line=[str(external), "-config", str(tmp_path / "other.toml")],
                accessible=True,
            )
        ],
        port_inspector=StaticPortInspector(),  # type: ignore[arg-type]
        path_lookup=lambda _name: None,
        supervisor_probe=lambda: False,
    )
    state = detector.detect(
        target_port=59020,
        target_config_path=tmp_path / "target.toml",
    )
    assert state.external_process_running is True
    assert state.external_configuration_detected is False
    assert state.conflict is False


def test_same_port_same_config_or_supervisor_blocks(tmp_path):
    external = tmp_path / "external" / "cc-connect.exe"
    target = tmp_path / "target.toml"
    observation = ProcessObservation(
        pid=502,
        executable=str(external),
        command_line=[str(external), "-config", str(target)],
        accessible=True,
    )
    detector = CcConnectExternalDetector(
        tmp_path / "product",
        process_provider=lambda: [observation],
        port_inspector=StaticPortInspector(owner_pid=502),  # type: ignore[arg-type]
        path_lookup=lambda _name: None,
        supervisor_probe=lambda: False,
    )
    state = detector.detect(target_port=59020, target_config_path=target)
    assert state.external_port_active is True
    assert state.external_configuration_detected is True
    assert state.conflict is True

    supervised = CcConnectExternalDetector(
        tmp_path / "product",
        process_provider=lambda: [],
        port_inspector=StaticPortInspector(),  # type: ignore[arg-type]
        path_lookup=lambda _name: None,
        supervisor_probe=lambda: True,
    ).detect()
    assert supervised.external_supervisor_detected is True
    assert supervised.conflict is True


def test_product_process_and_same_name_non_target_do_not_false_positive(tmp_path):
    product_exe = tmp_path / "product" / "versions" / "a" / "cc-connect.exe"
    other_exe = tmp_path / "other" / "cc-connect-helper.exe"
    observations = [
        ProcessObservation(
            pid=601,
            executable=str(product_exe),
            command_line=[str(product_exe)],
            accessible=True,
        ),
        ProcessObservation(
            pid=602,
            executable=str(other_exe),
            command_line=[str(other_exe)],
            accessible=True,
        ),
    ]
    state = CcConnectExternalDetector(
        tmp_path / "product",
        process_provider=lambda: observations,
        port_inspector=StaticPortInspector(),  # type: ignore[arg-type]
        path_lookup=lambda _name: None,
        supervisor_probe=lambda: False,
    ).detect(target_port=59020)
    assert state.external_process_running is False
    assert state.conflict is False


def test_inaccessible_process_is_reported_unknown_without_destructive_guess(tmp_path):
    state = CcConnectExternalDetector(
        tmp_path / "product",
        process_provider=lambda: [
            ProcessObservation(pid=700, executable=None, command_line=None, accessible=False)
        ],
        port_inspector=StaticPortInspector(unknown=True),  # type: ignore[arg-type]
        path_lookup=lambda _name: None,
        supervisor_probe=lambda: "unknown",
    ).detect(target_port=59020)
    assert state.unknown is True
    assert state.external_process_running == "unknown"
    assert state.conflict is False

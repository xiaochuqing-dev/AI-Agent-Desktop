from __future__ import annotations

from pathlib import Path

import pytest

from control_plane.installer.artifacts import InstallerError
from control_plane.installer.paths import ComponentLayout, atomic_write_json


def test_chinese_space_and_parentheses_path_support(tmp_path):
    layout = ComponentLayout(str(tmp_path / "隔离 Local AppData (测试)" / "components"))
    layout.ensure()
    pointer = {
        "schema_version": "1.0",
        "artifact_id": "cc-connect-test",
        "version": "test",
        "artifact_sha256": "a" * 64,
        "previous_artifact_id": None,
    }
    layout.write_current(pointer)
    assert layout.read_current() == pointer
    assert layout.current_file.read_bytes().startswith(b"{")


def test_long_windows_path_support(tmp_path):
    root = tmp_path
    identifier = "cc-connect-long-path-test"
    planned = root / "components" / "cc-connect" / "versions" / identifier / "cc-connect.exe"
    if len(str(planned)) < 225:
        prefix = "long-path-中文-"
        padding = 225 - len(str(planned)) - len(prefix) - 1
        root /= prefix + ("x" * padding)
        planned = root / "components" / "cc-connect" / "versions" / identifier / "cc-connect.exe"
    assert len(str(planned)) < 250
    layout = ComponentLayout(str(root / "components"))
    layout.ensure()
    target = layout.version_dir(identifier)
    target.mkdir()
    (target / "cc-connect.exe").write_bytes(b"test")
    assert (target / "cc-connect.exe").read_bytes() == b"test"


@pytest.mark.parametrize("identifier", ["../escape", "a/b", "a\\b", "", ".hidden"])
def test_identifier_path_traversal_is_blocked(tmp_path, identifier):
    layout = ComponentLayout(str(tmp_path / "components"))
    with pytest.raises(InstallerError) as captured:
        layout.version_dir(identifier)
    assert captured.value.code == "PATH_IDENTIFIER_INVALID"


@pytest.mark.parametrize("relative", ["../outside", "/absolute", "versions/../../outside"])
def test_persisted_cleanup_path_cannot_escape_root(tmp_path, relative):
    layout = ComponentLayout(str(tmp_path / "components"))
    with pytest.raises(InstallerError) as captured:
        layout.from_relative(relative)
    assert captured.value.code == "PATH_TRAVERSAL_BLOCKED"


def test_invalid_current_pointer_is_rejected(tmp_path):
    layout = ComponentLayout(str(tmp_path / "components"))
    layout.ensure()
    layout.current_file.write_text('{"artifact_id":"../escape"}', encoding="utf-8")
    with pytest.raises(InstallerError) as captured:
        layout.read_current()
    assert captured.value.code == "CURRENT_POINTER_INVALID"


def test_atomic_replace_failure_preserves_previous_state(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    target.write_text("old", encoding="utf-8")

    def fail_replace(_source: Path, _target: Path) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr("control_plane.installer.paths.os.replace", fail_replace)
    with pytest.raises(InstallerError) as captured:
        atomic_write_json(target, {"new": True})
    assert captured.value.code == "ATOMIC_WRITE_FAILED"
    assert target.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".state.json.*.tmp"))


def test_managed_target_symlink_is_rejected_when_supported(tmp_path):
    layout = ComponentLayout(str(tmp_path / "components"))
    layout.ensure()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = layout.versions / "linked"
    try:
        target.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable for this Windows account")
    with pytest.raises(InstallerError) as captured:
        layout.version_dir("linked")
    assert captured.value.code == "PATH_TRAVERSAL_BLOCKED" or captured.value.code == (
        "INSTALL_PATH_UNSAFE"
    )

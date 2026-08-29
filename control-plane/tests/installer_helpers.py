from __future__ import annotations

import json
import struct
from pathlib import Path

from control_plane.installer.artifacts import load_artifact_lock, sha256_bytes
from control_plane.installer.models import ArtifactManifest


def make_pe(machine: int = 0x8664, *, size: int = 1024) -> bytes:
    payload = bytearray(size)
    payload[:2] = b"MZ"
    struct.pack_into("<I", payload, 0x3C, 0x80)
    payload[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", payload, 0x84, machine)
    return bytes(payload)


def manifest_payload(artifact: bytes) -> dict:
    lock = load_artifact_lock()
    short_commit = lock["source_commit"][:7]
    ldflags = (
        lock["build"]["ldflags_template"]
        .replace("{version}", lock["version"])
        .replace("{short_commit}", short_commit)
        .replace("{build_timestamp}", lock["build"]["build_timestamp"])
    )
    return {
        "schema_version": lock["schema_version"],
        "component_id": lock["component_id"],
        "artifact_id": lock["artifact_id"],
        "platform": lock["toolchain"]["goos"],
        "architecture": lock["toolchain"]["goarch"],
        "source_repo": lock["source_repo"],
        "source_commit": lock["source_commit"],
        "upstream_version": lock["upstream_version"],
        "version": lock["version"],
        "patchset_version": lock["patchset_version"],
        "patch_files": lock["patch_files"],
        "patch_sha256": [item["sha256"] for item in lock["patch_files"]],
        "go_version": lock["toolchain"]["go_version"],
        "build_tags": lock["build"]["build_tags"],
        "ldflags": ldflags,
        "source_date_epoch": lock["build"]["source_date_epoch"],
        "build_timestamp_policy": "locked_upstream_commit_timestamp_utc",
        "artifact_filename": lock["artifact_filename"],
        "artifact_size": len(artifact),
        "artifact_sha256": sha256_bytes(artifact),
        "signature_status": lock["signature_status"],
        "created_at": lock["build"]["build_timestamp"],
        "compatibility": lock["compatibility"],
        "minimum_os": lock["minimum_os"],
        "install_layout_version": lock["install_layout_version"],
        "health_probe_version": lock["health_probe_version"],
        "health_probe": {
            "mode": "version_only",
            "deep_health": "unsupported",
            "network_access": "none",
        },
    }


def write_test_bundle(
    root: Path, *, machine: int = 0x8664, artifact: bytes | None = None
) -> tuple[Path, ArtifactManifest]:
    root.mkdir(parents=True, exist_ok=True)
    artifact = artifact if artifact is not None else make_pe(machine)
    payload = manifest_payload(artifact)
    manifest = ArtifactManifest.model_validate(payload)
    (root / manifest.artifact_filename).write_bytes(artifact)
    (root / "cc-connect-artifact-manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return root, manifest


def bind_test_artifact_lock(monkeypatch, manifest: ArtifactManifest) -> None:
    """Bind the product lock to a synthetic PE without weakening production checks."""

    test_lock = load_artifact_lock()
    test_lock["artifact_size"] = manifest.artifact_size
    test_lock["artifact_sha256"] = manifest.artifact_sha256
    monkeypatch.setattr(
        "control_plane.installer.artifacts.load_artifact_lock",
        lambda: test_lock,
    )

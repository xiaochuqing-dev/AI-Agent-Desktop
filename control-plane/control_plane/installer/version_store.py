from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ..persistence.models import ComponentVersionRecord
from ..persistence.session import Database
from .artifacts import ArtifactManifest, InstallerError, load_manifest, verify_artifact_file
from .paths import ComponentLayout


@dataclass(frozen=True)
class InstalledArtifact:
    artifact_id: str
    version: str
    executable: Path
    artifact_sha256: str
    manifest: ArtifactManifest
    current_pointer: dict


class ManagedVersionStore:
    """Read and verify product-owned version state without lifecycle side effects."""

    def __init__(self, layout: ComponentLayout, database: Database) -> None:
        self.layout = layout
        self.database = database

    def current(self) -> InstalledArtifact:
        pointer = self.layout.read_current()
        if pointer is None:
            raise InstallerError(
                "MANAGED_VERSION_NOT_INSTALLED",
                "No product-managed cc-connect version is active.",
                recovery_actions=["install_cc_connect"],
            )
        artifact_id = str(pointer["artifact_id"])
        with self.database.session() as session:
            record = session.get(ComponentVersionRecord, artifact_id)
            if record is None or record.status != "installed":
                raise InstallerError(
                    "MANAGED_VERSION_RECORD_MISSING",
                    "The active version has no valid product install record.",
                    recovery_actions=["repair_product_installation"],
                )
        version_dir = self.layout.version_dir(artifact_id)
        manifest, _ = load_manifest(
            version_dir / "cc-connect-artifact-manifest.json", enforce_lock=False
        )
        executable = version_dir / manifest.artifact_filename
        verify_artifact_file(executable, manifest)
        if (
            manifest.artifact_id != artifact_id
            or manifest.artifact_sha256 != pointer["artifact_sha256"]
            or record.artifact_sha256 != manifest.artifact_sha256
            or record.relative_path != f"versions/{artifact_id}"
        ):
            raise InstallerError(
                "MANAGED_VERSION_INTEGRITY_FAILURE",
                "The active version pointer, manifest, artifact, and install record disagree.",
                recovery_actions=["repair_product_installation", "restore_previous_version"],
            )
        return InstalledArtifact(
            artifact_id=artifact_id,
            version=manifest.version,
            executable=executable.resolve(strict=True),
            artifact_sha256=manifest.artifact_sha256,
            manifest=manifest,
            current_pointer=pointer,
        )

    def context_digest(self) -> str:
        artifact = self.current()
        payload = json.dumps(
            artifact.current_pointer,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(payload).hexdigest()

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from control_plane.credentials.models import CredentialStatus
from control_plane.credentials.service import CredentialService
from control_plane.credentials.windows_backend import WindowsCredentialManagerBackend
from control_plane.infrastructure.config import Settings
from control_plane.persistence.session import Database


def _contains_secret(root: Path, secrets: tuple[str, ...]) -> list[str]:
    encoded = [
        value.encode(encoding)
        for value in secrets
        for encoding in ("utf-8", "utf-16-le", "utf-16-be")
    ]
    leaks: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if any(value in data for value in encoded):
            leaks.append(str(path.relative_to(root)))
    return sorted(leaks)


def run() -> dict[str, Any]:
    if sys.platform != "win32":
        raise RuntimeError("Windows Credential Manager acceptance requires Windows")

    started_at = datetime.now(UTC)
    reference_id = f"acceptance/windows-credential-{uuid.uuid4().hex}"
    first_secret = f"AIAD-SYNTHETIC-FIRST-{uuid.uuid4().hex}"
    second_secret = f"AIAD-SYNTHETIC-SECOND-{uuid.uuid4().hex}"
    backend = WindowsCredentialManagerBackend()
    capability = backend.probe()
    if capability.status != CredentialStatus.AVAILABLE or not capability.native_windows_backend:
        raise AssertionError(capability.model_dump_json())
    if capability.evidence.get("plaintext_file_fallback_allowed") is not False:
        raise AssertionError("plaintext fallback was not explicitly forbidden")

    is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    with tempfile.TemporaryDirectory(prefix="AIAD credential acceptance 中文 (临时) ") as root_name:
        root = Path(root_name)
        settings = Settings(data_dir=str(root / "control-plane-data"))
        database = Database(settings)
        service = CredentialService(database, backend)
        initial_status = backend.status(reference_id)
        if initial_status != CredentialStatus.MISSING:
            raise AssertionError(f"fresh acceptance reference is not missing: {initial_status}")

        try:
            created = service.put(reference_id, first_secret, operation_id="acceptance-put")
            if created.revision != 1 or created.status != CredentialStatus.AVAILABLE:
                raise AssertionError(created.model_dump_json())
            with service.resolve_for_operation(reference_id) as resolved:
                if resolved != first_secret:
                    raise AssertionError("initial credential resolve mismatch")

            replaced = service.replace(
                reference_id,
                second_secret,
                operation_id="acceptance-replace",
            )
            if replaced.revision != 2 or replaced.status != CredentialStatus.AVAILABLE:
                raise AssertionError(replaced.model_dump_json())
            with service.resolve_for_operation(reference_id) as resolved:
                if resolved != second_secret or resolved == first_secret:
                    raise AssertionError("replacement credential resolve mismatch")

            metadata_status = backend.list_metadata([reference_id])[reference_id]
            if metadata_status != CredentialStatus.AVAILABLE:
                raise AssertionError(f"metadata status mismatch: {metadata_status}")

            deleted = service.delete(reference_id, operation_id="acceptance-delete")
            if deleted.revision != 3 or deleted.status != CredentialStatus.MISSING:
                raise AssertionError(deleted.model_dump_json())
            if backend.status(reference_id) != CredentialStatus.MISSING:
                raise AssertionError("credential remained after explicit delete")

            leaks = _contains_secret(root, (first_secret, second_secret))
            if leaks:
                raise AssertionError(f"synthetic credential leaked to product files: {leaks}")

            return {
                "status": "PASSED",
                "started_at": started_at.isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
                "platform": sys.platform,
                "windows_version": "win32:"
                + ".".join(str(part) for part in sys.getwindowsversion().platform_version),
                "ordinary_user_observed": not is_admin,
                "is_admin": is_admin,
                "reference_id": reference_id,
                "backend_capability": capability.model_dump(mode="json"),
                "initial_status": initial_status.value,
                "put_revision": created.revision,
                "replace_revision": replaced.revision,
                "delete_revision": deleted.revision,
                "final_status": CredentialStatus.MISSING.value,
                "resolve_verified": True,
                "metadata_only_verified": True,
                "product_file_plaintext_scan": "passed",
                "plaintext_file_fallback_allowed": False,
                "physical_memory_zeroing_guaranteed": False,
                "synthetic_secret_only": True,
            }
        finally:
            if backend.status(reference_id) == CredentialStatus.AVAILABLE:
                backend.delete(reference_id)
            database.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

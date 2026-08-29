"""Validate the Windows GUI candidate produced by ``build_windows_candidate.ps1``.

The validator intentionally performs only local checks.  It never contacts
Telegram (or any other service); the executable smoke checks are limited to
the ``--version`` and ``--headless`` paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NoReturn

EXPECTED_MANIFEST = {
    "schema_version": "1",
    "candidate_version": "0.4.1-prebeta",
    "product": "AI-Agent-Desktop",
    "platform": "windows",
    "architecture": "x64",
    "minimum_os": "Windows 10",
    "python_embedded": True,
    "go_embedded": False,
    "node_embedded": False,
    "black_window": False,
    "changes_external_environment": False,
    "chrome_agent_required": False,
}

EXPECTED_CC_CONNECT = {
    "artifact_id": "cc-connect-v1.5.0-patchset0.2-17c6106-windows-amd64",
    "version": "v1.5.0-patchset0.2-17c6106",
    "source_commit": "17c61062c2f9ce9bcdd45a2082e491f9743a2770",
    "upstream_version": "1.5.0",
    "patchset_version": "0.2",
    "artifact_size": 54266368,
    "artifact_sha256": "67a127b6c59b942058ed2bd8c6237ff613e37eb3df64e7cd6ea0c18f3c418144",
    "renderer_version": "cc-connect-17c6106-native-v2",
}

EXPECTED_PATCH_FILES = (
    "001-telegram-directed-routing.patch",
    "002-hook-config-headers.patch",
    "003-relay-response-prefix.patch",
    "004-message-delivery-hooks.patch",
)

METADATA_FILES = {
    "candidate-manifest.json",
    "candidate-manifest.sha256",
    "candidate-package.sha256",
    "SHA256SUMS.txt",
}

REQUIRED_PAYLOAD_FILES = {
    ".python-version",
    "AI-Agent-Desktop.exe",
    "artifact-lock.json",
    "production_only_acceptance.py",
    "requirements-build.lock",
    "requirements-gui.lock",
    "requirements-prod.lock",
    "USER_VALIDATION_GUIDE.txt",
    "windows10_user_acceptance.ps1",
    "cc-connect/cc-connect.exe",
    "cc-connect/cc-connect-artifact-manifest.json",
    "cc-connect/cc-connect.sha256",
}

CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64})\s{2}(.+?)\s*$")

# These patterns are deliberately specific.  In particular, do not reject a
# harmless field or the word ``token`` by itself: the GUI candidate contains
# synthetic smoke-test names and redaction rule examples.
SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("telegram-bot-token", re.compile(rb"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")),
    ("openai-key", re.compile(rb"\bsk-(?!ant-)[A-Za-z0-9_-]{20,}\b")),
    ("anthropic-key", re.compile(rb"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
)

TEXT_FILE_SUFFIXES = frozenset(
    {
        ".cfg",
        ".html",
        ".ini",
        ".json",
        ".lock",
        ".md",
        ".ps1",
        ".py",
        ".sha256",
        ".toml",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)
VERIFIED_EXTERNAL_BINARIES = frozenset({"cc-connect/cc-connect.exe"})


class ValidationError(RuntimeError):
    """A candidate failed a release gate."""


def _fail(message: str) -> NoReturn:
    raise ValidationError(message)


def _normalise_relative(value: str) -> str:
    """Return a safe, slash-separated relative path for comparisons."""

    if not isinstance(value, str) or not value:
        _fail("manifest contains an empty or non-string relative path")
    normalised = value.replace("\\", "/")
    pure = PurePosixPath(normalised)
    windows = PureWindowsPath(value)
    if pure.is_absolute() or windows.is_absolute() or windows.drive or ".." in pure.parts:
        _fail(f"manifest path escapes candidate root: {value!r}")
    return "/".join(part for part in pure.parts if part not in ("", "."))


def _path_from_relative(root: Path, value: str) -> Path:
    normalised = _normalise_relative(value)
    return root.joinpath(*normalised.split("/"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"cannot read JSON {path.name}: {exc}")
    if not isinstance(value, dict):
        _fail(f"JSON root must be an object: {path.name}")
    return value


def _parse_checksum_line(path: Path, expected_name: str) -> str:
    try:
        lines = [
            line.strip() for line in path.read_text(encoding="ascii").splitlines() if line.strip()
        ]
    except (OSError, UnicodeError) as exc:
        _fail(f"cannot read checksum file {path.name}: {exc}")
    if len(lines) != 1:
        _fail(f"checksum file must contain exactly one line: {path.name}")
    match = CHECKSUM_RE.fullmatch(lines[0])
    if not match or match.group(2).replace("\\", "/") != expected_name:
        _fail(f"invalid checksum line in {path.name}")
    return match.group(1).lower()


def _parse_sha256sums(path: Path) -> dict[str, str]:
    try:
        lines = [line.rstrip("\r\n") for line in path.read_text(encoding="ascii").splitlines()]
    except (OSError, UnicodeError) as exc:
        _fail(f"cannot read SHA256SUMS.txt: {exc}")
    result: dict[str, str] = {}
    for line in lines:
        if not line.strip():
            continue
        match = CHECKSUM_RE.fullmatch(line)
        if not match:
            _fail(f"invalid SHA256SUMS.txt line: {line!r}")
        relative = _normalise_relative(match.group(2))
        if relative in result:
            _fail(f"duplicate SHA256SUMS.txt path: {relative}")
        result[relative] = match.group(1).lower()
    if not result:
        _fail("SHA256SUMS.txt is empty")
    return result


def _validate_manifest_and_hashes(candidate: Path) -> dict[str, object]:
    manifest_path = candidate / "candidate-manifest.json"
    manifest_hash_path = candidate / "candidate-manifest.sha256"
    package_hash_path = candidate / "candidate-package.sha256"
    sums_path = candidate / "SHA256SUMS.txt"
    for path in (manifest_path, manifest_hash_path, package_hash_path, sums_path):
        if not path.is_file():
            _fail(f"candidate metadata file is missing: {path.name}")

    manifest_hash = _parse_checksum_line(manifest_hash_path, "candidate-manifest.json")
    actual_manifest_hash = _sha256(manifest_path)
    if manifest_hash != actual_manifest_hash:
        _fail("candidate-manifest.sha256 does not match candidate-manifest.json")

    manifest = _read_json(manifest_path)
    for key, expected in EXPECTED_MANIFEST.items():
        if manifest.get(key) != expected:
            _fail(f"manifest field {key!r} must be {expected!r}")
    for key in (
        "cc_connect_artifact_id",
        "cc_connect_version",
        "cc_connect_source_commit",
        "cc_connect_patchset_version",
        "cc_connect_artifact_sha256",
        "cc_connect_renderer_version",
        "cc_connect_renderer_source_commit",
        "package_sha256",
    ):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            _fail(f"manifest field {key!r} is missing or empty")
    if manifest.get("cc_connect_active_patch_count") != len(EXPECTED_PATCH_FILES):
        _fail("manifest cc_connect_active_patch_count mismatch")

    raw_entries = manifest.get("files")
    if not isinstance(raw_entries, list) or not raw_entries:
        _fail("manifest files must be a non-empty list")

    entries: list[tuple[str, str, int, str]] = []
    seen: set[str] = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            _fail("manifest files contains a non-object entry")
        raw_path = raw_entry.get("path")
        if not isinstance(raw_path, str):
            _fail(f"manifest path is not a string: {raw_path!r}")
        relative = _normalise_relative(raw_path)
        if not relative or relative in seen:
            _fail(f"duplicate or invalid manifest path: {raw_path!r}")
        seen.add(relative)
        digest = raw_entry.get("sha256")
        size = raw_entry.get("size")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            _fail(f"invalid SHA256 in manifest entry: {raw_path!r}")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            _fail(f"invalid size in manifest entry: {raw_path!r}")
        target = _path_from_relative(candidate, relative)
        if not target.is_file():
            _fail(f"manifest file is missing: {relative}")
        if target.stat().st_size != size:
            _fail(f"size mismatch for {relative}")
        actual = _sha256(target)
        if actual != digest.lower():
            _fail(f"SHA256 mismatch for {relative}")
        entries.append((relative, digest.lower(), size, raw_path))

    actual_payload = {
        path.relative_to(candidate).as_posix()
        for path in candidate.rglob("*")
        if path.is_file() and path.relative_to(candidate).as_posix() not in METADATA_FILES
    }
    if actual_payload != seen:
        missing = sorted(seen - actual_payload)
        extra = sorted(actual_payload - seen)
        _fail(f"manifest payload set mismatch (missing={missing}, extra={extra})")

    # The builder's canonical basis preserves the PowerShell ``Sort-Object
    # FullName`` order recorded in the manifest.  Keep that exact order when
    # recomputing the package digest; normalizing it with Python's sort would
    # produce a different hash for paths containing punctuation.
    canonical = "".join(f"{digest}  {raw_path}\n" for _, digest, _, raw_path in entries).encode(
        "utf-8"
    )
    package_hash = hashlib.sha256(canonical).hexdigest()
    if package_hash != str(manifest["package_sha256"]).lower():
        _fail("manifest package_sha256 does not match the canonical payload")
    package_file_hash = _parse_checksum_line(package_hash_path, "payload")
    if package_file_hash != package_hash:
        _fail("candidate-package.sha256 does not match the canonical payload")

    sums = _parse_sha256sums(sums_path)
    actual_sums_paths = {
        path.relative_to(candidate).as_posix()
        for path in candidate.rglob("*")
        if path.is_file() and path.relative_to(candidate).as_posix() != "SHA256SUMS.txt"
    }
    if set(sums) != actual_sums_paths:
        _fail("SHA256SUMS.txt path set does not match candidate files")
    for relative, expected in sums.items():
        actual = _sha256(_path_from_relative(candidate, relative))
        if actual != expected:
            _fail(f"SHA256SUMS.txt mismatch for {relative}")

    return manifest


def _validate_required_files(candidate: Path, manifest: dict[str, object]) -> dict[str, object]:
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list):
        _fail("manifest files must be a list")
    manifest_paths = {
        _normalise_relative(entry["path"])
        for entry in raw_files
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    for relative in REQUIRED_PAYLOAD_FILES:
        if relative not in manifest_paths:
            _fail(f"required payload file is not listed: {relative}")
        if not _path_from_relative(candidate, relative).is_file():
            _fail(f"required payload file is missing: {relative}")

    cc_dir = candidate / "cc-connect"
    artifact_lock = _read_json(candidate / "artifact-lock.json")
    cc_manifest = _read_json(cc_dir / "cc-connect-artifact-manifest.json")
    cc_exe = cc_dir / "cc-connect.exe"
    cc_digest = _parse_checksum_line(cc_dir / "cc-connect.sha256", "cc-connect.exe")
    if cc_digest != _sha256(cc_exe):
        _fail("cc-connect.sha256 does not match cc-connect.exe")
    if cc_digest != str(manifest["cc_connect_artifact_sha256"]).lower():
        _fail("candidate manifest cc_connect_artifact_sha256 mismatch")
    if cc_exe.stat().st_size != EXPECTED_CC_CONNECT["artifact_size"]:
        _fail("cc-connect executable size does not match the locked artifact")

    for key, expected in EXPECTED_CC_CONNECT.items():
        if key == "renderer_version":
            continue
        if artifact_lock.get(key) != expected:
            _fail(f"artifact lock field {key!r} must be {expected!r}")
    patch_files = artifact_lock.get("patch_files")
    if not isinstance(patch_files, list):
        _fail("artifact lock patch_files must be a list")
    patch_names = tuple(item.get("filename") for item in patch_files if isinstance(item, dict))
    if patch_names != EXPECTED_PATCH_FILES:
        _fail(f"artifact lock active patch list mismatch: {patch_names!r}")
    if any(name.startswith("005-") for name in patch_names):
        _fail("retired Patch 005 is still active")

    for key in (
        "artifact_id",
        "version",
        "source_commit",
        "upstream_version",
        "patchset_version",
        "artifact_size",
        "artifact_sha256",
        "patch_files",
    ):
        if cc_manifest.get(key) != artifact_lock.get(key):
            _fail(f"cc-connect manifest and artifact lock differ for {key}")
    for key in ("artifact_id", "version", "source_commit", "patchset_version"):
        if str(cc_manifest.get(key, "")) != str(manifest[f"cc_connect_{key}"]):
            _fail(f"cc-connect manifest {key} mismatch")
    if manifest.get("cc_connect_active_patch_count") != len(patch_files):
        _fail("candidate manifest active patch count differs from artifact lock")
    if manifest.get("cc_connect_renderer_version") != EXPECTED_CC_CONNECT["renderer_version"]:
        _fail("candidate renderer version is not locked to v1.5.0")
    if manifest.get("cc_connect_renderer_source_commit") != EXPECTED_CC_CONNECT["source_commit"]:
        _fail("candidate renderer source commit is not locked to v1.5.0")
    return cc_manifest


def _run_executable_smoke(executable: Path, expected_version: str) -> None:
    child_env = os.environ.copy()
    child_env["CONTROL_PLANE_DISABLE_LIVE_TELEGRAM"] = "1"
    child_env["QT_QPA_PLATFORM"] = "offscreen"
    for key in tuple(child_env):
        if key.startswith("TELEGRAM_") or key in {
            "CONTROL_PLANE_API_TOKEN",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        }:
            child_env.pop(key, None)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for argument in ("--version", "--headless"):
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                [str(executable), argument],
                cwd=executable.parent,
                env=child_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
            stdout, _stderr = process.communicate(timeout=45)
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                _terminate_process_tree(process)
            _fail(f"GUI executable {argument} smoke failed: {type(exc).__name__}")
        except OSError as exc:
            _fail(f"GUI executable {argument} smoke failed: {type(exc).__name__}")
        if process is None or process.returncode != 0:
            return_code = process.returncode if process is not None else None
            _fail(f"GUI executable {argument} smoke returned {return_code}")
        output = stdout.decode("utf-8", errors="replace").strip()
        if argument == "--version" and output != expected_version:
            _fail(f"GUI executable version output mismatch: {output!r}")
        if argument == "--headless":
            try:
                headless = json.loads(output)
            except json.JSONDecodeError:
                _fail("GUI executable headless output is not JSON")
            if headless.get("status") != "ready" or headless.get("version") != expected_version:
                _fail("GUI executable headless release facts mismatch")


def _run_cc_connect_version_smoke(executable: Path, manifest: dict[str, object]) -> None:
    child_env = {
        "SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
        "WINDIR": os.environ.get("WINDIR", r"C:\Windows"),
        "PATH": os.environ.get("SystemRoot", r"C:\Windows") + r"\System32",
        "NO_PROXY": "*",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "ALL_PROXY": "",
    }
    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            cwd=executable.parent,
            env=child_env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _fail(f"cc-connect --version smoke failed: {type(exc).__name__}")
    output = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
    version = str(manifest.get("version", ""))
    commit = str(manifest.get("source_commit", ""))[:7]
    if completed.returncode != 0 or version not in output or commit not in output:
        _fail("cc-connect --version does not expose the locked version and source commit")


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    if process.poll() is None:
        process.kill()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _validate_pe_subsystem(executable: Path) -> None:
    try:
        import pefile

        pe = pefile.PE(str(executable), fast_load=True)
        machine = int(pe.FILE_HEADER.Machine)
        subsystem = int(pe.OPTIONAL_HEADER.Subsystem)
        pe.close()
    except Exception as exc:  # pragma: no cover - exercised on Windows CI
        _fail(f"cannot parse GUI executable PE headers: {type(exc).__name__}")
    if machine != 0x8664:  # IMAGE_FILE_MACHINE_AMD64.
        _fail(f"GUI executable has PE machine 0x{machine:04x}, expected AMD64")
    if subsystem != 2:  # IMAGE_SUBSYSTEM_WINDOWS_GUI; no console window.
        _fail(f"GUI executable has PE subsystem {subsystem}, expected 2")


def _normalise_archive_name(value: str) -> str:
    return value.replace("\\", "/").strip("/").lower()


def _looks_like_binary_telegram_token(match: re.Match[bytes]) -> bool:
    """Avoid treating lookup-table bytes as a credential in compiled binaries."""

    secret = match.group(0).split(b":", 1)[1]
    if len(secret) > 64:
        return False
    if b"AcceptanceCanary" in secret or b"NotAReal" in secret:
        return False
    if not (
        any(65 <= value <= 90 for value in secret)
        and any(97 <= value <= 122 for value in secret)
        and any(48 <= value <= 57 for value in secret)
    ):
        return False
    for index in range(len(secret) - 7):
        window = secret[index : index + 8]
        if all(window[offset + 1] == window[offset] + 1 for offset in range(7)):
            return False
        if all(window[offset + 1] == window[offset] - 1 for offset in range(7)):
            return False
    return True


def _scan_sensitive(
    label: str, payload: bytes, findings: list[str], *, binary: bool = False
) -> None:
    for name, pattern in SENSITIVE_PATTERNS:
        matches = pattern.finditer(payload)
        if binary and name == "telegram-bot-token":
            matches = (match for match in matches if _looks_like_binary_telegram_token(match))
        if next(matches, None) is not None:
            findings.append(f"{label}:{name}")


def _validate_archive(executable: Path, findings: list[str]) -> None:
    try:
        from PyInstaller.archive.readers import CArchiveReader

        reader = CArchiveReader(str(executable))
    except Exception as exc:  # pragma: no cover - exercised on Windows CI
        _fail(f"cannot read PyInstaller CArchive: {type(exc).__name__}")

    names = {_normalise_archive_name(name): name for name in reader.toc}
    required_exact = (
        "control_plane/gui/assets/app_icon.ico",
        "control_plane/gui/assets/app_icon.png",
        "alembic.ini",
    )
    for required in required_exact:
        if required not in names:
            _fail(f"PyInstaller archive is missing {required}")
    if not any(name.startswith("alembic/versions/") for name in names):
        _fail("PyInstaller archive is missing alembic/versions")
    if not any("/platforms/" in name and name.endswith("/qwindows.dll") for name in names):
        _fail("PyInstaller archive is missing the Qt Windows platform plugin")

    required_icons = {
        f"control_plane/gui/icons/assets/{name}.svg"
        for name in (
            "arrow-left",
            "arrow-right",
            "claude",
            "clipboard",
            "close",
            "codex",
            "eye-off",
            "eye",
            "group",
            "hermes",
            "info",
            "maximize",
            "minimize",
            "qr",
            "refresh",
            "repair",
            "restore",
            "shield",
            "success",
            "telegram",
            "warning",
            "error",
        )
    }
    missing_icons = sorted(required_icons - set(names))
    if missing_icons:
        _fail(f"PyInstaller archive is missing GUI SVG assets: {missing_icons}")

    for original_name in reader.toc:
        try:
            reader.extract(original_name)
        except Exception as exc:
            _fail(f"cannot extract PyInstaller entry {original_name!r}: {type(exc).__name__}")

    # Python modules live in a nested PYZ archive.  Scan their decompressed
    # bytecode as well, because secrets can be hidden by the zlib layer.
    nested_module_names: set[str] = set()
    for original_name, entry in reader.toc.items():
        if entry[-1] != "z":
            continue
        try:
            nested = reader.open_embedded_archive(original_name)
            for module_name in nested.toc:
                nested_module_names.add(str(module_name).lower())
                payload = nested.extract(module_name, raw=True)
                normalised_module = str(module_name).lower()
                if payload is not None and (
                    normalised_module == "control_plane"
                    or normalised_module.startswith("control_plane.")
                ):
                    _scan_sensitive(
                        f"archive:{original_name}:{module_name}", payload, findings, binary=True
                    )
        except Exception as exc:
            _fail(f"cannot read nested PyInstaller archive {original_name!r}: {type(exc).__name__}")
    if not any(
        name == "control_plane" or name.startswith("control_plane.") for name in nested_module_names
    ):
        _fail("PyInstaller archive is missing embedded Control Plane modules")
    if not any(name == "control_plane.gui.app" for name in nested_module_names):
        _fail("PyInstaller archive is missing the formal GUI module")
    required_modules = {
        "control_plane.agent_detection.models",
        "control_plane.agent_detection.probe",
        "control_plane.agent_detection.service",
        "control_plane.agent_detection.windows_discovery",
        "control_plane.observability.service",
        "control_plane.gui.main_window",
        "control_plane.gui.icons.registry",
        "control_plane.gui.icons.renderer",
        "control_plane.hermes.cli",
        "control_plane.hermes.env_transaction",
        "control_plane.hermes.lifecycle",
        "control_plane.hermes.models",
        "control_plane.hermes.service",
    }
    missing_modules = sorted(required_modules - nested_module_names)
    if missing_modules:
        _fail(f"PyInstaller archive is missing pre-beta closure modules: {missing_modules}")
    if not (
        any(name == "qrcode" or name.startswith("qrcode.") for name in nested_module_names)
        or any(name == "qrcode" or name.startswith("qrcode/") for name in names)
    ):
        _fail("PyInstaller archive is missing embedded qrcode modules")


def _scan_candidate_files(candidate: Path, findings: list[str]) -> None:
    for path in sorted(candidate.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file():
            continue
        relative = path.relative_to(candidate).as_posix()
        if relative in VERIFIED_EXTERNAL_BINARIES:
            continue
        if path.name != ".python-version" and path.suffix.lower() not in TEXT_FILE_SUFFIXES:
            continue
        try:
            payload = path.read_bytes()
        except OSError as exc:
            _fail(f"cannot read candidate file {path.name}: {exc}")
        _scan_sensitive(f"file:{relative}", payload, findings)


def validate(candidate: Path) -> dict[str, object]:
    candidate = candidate.resolve()
    if not candidate.is_dir():
        _fail(f"candidate directory does not exist: {candidate}")
    manifest = _validate_manifest_and_hashes(candidate)
    cc_manifest = _validate_required_files(candidate, manifest)
    executable = candidate / "AI-Agent-Desktop.exe"
    _run_executable_smoke(executable, str(manifest["candidate_version"]))
    _run_cc_connect_version_smoke(candidate / "cc-connect" / "cc-connect.exe", cc_manifest)
    _validate_pe_subsystem(executable)
    findings: list[str] = []
    _scan_candidate_files(candidate, findings)
    _validate_archive(executable, findings)
    if findings:
        _fail("sensitive credential pattern found: " + ", ".join(sorted(set(findings))[:20]))
    return {
        "status": "passed",
        "candidate": str(candidate),
        "candidate_version": manifest["candidate_version"],
        "package_sha256": manifest["package_sha256"],
        "archive_entries": "checked",
        "real_telegram_access": False,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate an AI-Agent-Desktop GUI candidate directory"
    )
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = validate(args.candidate)
    except ValidationError as exc:
        print(f"GUI candidate validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

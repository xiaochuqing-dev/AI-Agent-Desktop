from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any

import psutil

from .models import ArtifactManifest

MANIFEST_FILENAME = "cc-connect-artifact-manifest.json"
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_CREATE_NEW_PROCESS_GROUP = 0x00000200 if sys.platform == "win32" else 0


class InstallerError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        recovery_actions: list[str] | None = None,
        technical_details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        self.recovery_actions = recovery_actions or []
        self.technical_details = technical_details or {}
        super().__init__(message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


CancelCheck = Callable[[], None]


def sha256_file(path: Path, *, cancel_check: CancelCheck | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if cancel_check:
                cancel_check()
            digest.update(chunk)
    return digest.hexdigest()


def load_artifact_lock() -> dict[str, Any]:
    lock_resource = files("control_plane.installer").joinpath("artifact-lock.json")
    return json.loads(lock_resource.read_text(encoding="utf-8"))


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_manifest_bytes(
    raw: bytes, *, max_bytes: int = 1024 * 1024, enforce_lock: bool = True
) -> ArtifactManifest:
    if not raw or len(raw) > max_bytes:
        raise InstallerError(
            "MANIFEST_SIZE_INVALID",
            "Artifact manifest is empty or exceeds the allowed size.",
            recovery_actions=["obtain_locked_manifest"],
        )
    try:
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_reject_duplicate_json_keys)
        manifest = ArtifactManifest.model_validate(payload)
    except Exception as exc:
        raise InstallerError(
            "MANIFEST_INVALID",
            "Artifact manifest failed schema validation.",
            recovery_actions=["obtain_locked_manifest"],
            technical_details={"validation": type(exc).__name__},
        ) from None
    if enforce_lock:
        validate_manifest_lock(manifest)
    return manifest


def load_manifest(path: Path, *, enforce_lock: bool = True) -> tuple[ArtifactManifest, bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InstallerError(
            "MANIFEST_UNAVAILABLE",
            "Artifact manifest could not be read.",
            retryable=True,
            recovery_actions=["retry_acquisition"],
            technical_details={"error": type(exc).__name__},
        ) from None
    return load_manifest_bytes(raw, enforce_lock=enforce_lock), raw


def validate_manifest_lock(manifest: ArtifactManifest) -> None:
    lock = load_artifact_lock()
    expected_patches = [(item["filename"], item["sha256"]) for item in lock["patch_files"]]
    actual_patches = [(item.filename, item.sha256) for item in manifest.patch_files]
    expected = {
        "component_id": lock["component_id"],
        "artifact_id": lock["artifact_id"],
        "platform": lock["toolchain"]["goos"],
        "architecture": lock["toolchain"]["goarch"],
        "source_repo": lock["source_repo"],
        "source_commit": lock["source_commit"],
        "upstream_version": lock["upstream_version"],
        "version": lock["version"],
        "patchset_version": lock["patchset_version"],
        "go_version": lock["toolchain"]["go_version"],
        "source_date_epoch": lock["build"]["source_date_epoch"],
        "build_timestamp_policy": "locked_upstream_commit_timestamp_utc",
        "artifact_filename": lock["artifact_filename"],
        "artifact_size": lock["artifact_size"],
        "artifact_sha256": lock["artifact_sha256"],
        "signature_status": lock["signature_status"],
        "install_layout_version": lock["install_layout_version"],
        "health_probe_version": lock["health_probe_version"],
        "minimum_os": lock["minimum_os"],
    }
    actual = {key: getattr(manifest, key) for key in expected}
    if actual != expected or actual_patches != expected_patches:
        raise InstallerError(
            "MANIFEST_LOCK_MISMATCH",
            "Artifact manifest does not match the product lock.",
            recovery_actions=["obtain_locked_artifact"],
        )
    short_commit = lock["source_commit"][:7]
    expected_ldflags = (
        lock["build"]["ldflags_template"]
        .replace("{version}", lock["version"])
        .replace("{short_commit}", short_commit)
        .replace("{build_timestamp}", lock["build"]["build_timestamp"])
    )
    if (
        manifest.schema_version != lock["schema_version"]
        or manifest.build_tags != lock["build"]["build_tags"]
        or manifest.ldflags != expected_ldflags
        or manifest.compatibility != lock["compatibility"]
        or manifest.created_at.isoformat().replace("+00:00", "Z")
        != lock["build"]["build_timestamp"]
        or manifest.health_probe
        != {"mode": "version_only", "deep_health": "unsupported", "network_access": "none"}
    ):
        raise InstallerError(
            "MANIFEST_BUILD_INPUT_MISMATCH",
            "Artifact build tags do not match the product lock.",
            recovery_actions=["obtain_locked_artifact"],
        )


def validate_download_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        parsed = urllib.parse.SplitResult("", "", "", "", "")
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not hostname
        or hostname not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
    ):
        raise InstallerError(
            "DOWNLOAD_URL_NOT_ALLOWED",
            "Artifact URL is not an approved credential-free HTTPS source.",
            recovery_actions=["use_locked_source"],
            technical_details={"host": hostname or "invalid"},
        )
    return url


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: tuple[str, ...]) -> None:
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        validate_download_url(newurl, self.allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ArtifactDownloader:
    def __init__(
        self,
        *,
        allowed_hosts: tuple[str, ...],
        timeout_seconds: int,
        retries: int,
    ) -> None:
        self.allowed_hosts = allowed_hosts
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(urllib.request.getproxies()),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            _ValidatedRedirectHandler(allowed_hosts),
        )

    def download(
        self,
        url: str,
        destination: Path,
        *,
        max_bytes: int,
        cancel_check: CancelCheck | None = None,
    ) -> Path:
        validate_download_url(url, self.allowed_hosts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        last_error: InstallerError | None = None
        for attempt in range(1, self.retries + 1):
            try:
                if cancel_check:
                    cancel_check()
                self._download_once(url, partial, max_bytes=max_bytes, cancel_check=cancel_check)
                os.replace(partial, destination)
                return destination
            except InstallerError as exc:
                last_error = exc
                if not exc.retryable or attempt == self.retries:
                    break
                time.sleep(min(0.25 * attempt, 1.0))
        assert last_error is not None
        raise last_error

    def _download_once(
        self,
        url: str,
        partial: Path,
        *,
        max_bytes: int,
        cancel_check: CancelCheck | None,
    ) -> None:
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > max_bytes:
            partial.unlink(missing_ok=True)
            raise InstallerError(
                "ARTIFACT_SIZE_LIMIT_EXCEEDED",
                "Partial artifact exceeds the allowed size.",
                recovery_actions=["discard_partial_download"],
            )
        headers = {"User-Agent": "AI-Agent-Desktop-Control-Plane/0.2"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                status = response.getcode()
                append = offset > 0 and status == 206
                if offset > 0 and not append:
                    offset = 0
                validate_download_url(response.geturl(), self.allowed_hosts)
                content_length = response.headers.get("Content-Length")
                try:
                    declared_length = int(content_length) if content_length else None
                except ValueError:
                    raise InstallerError(
                        "ARTIFACT_DOWNLOAD_INVALID_RESPONSE",
                        "Artifact server returned an invalid content length.",
                        retryable=True,
                        recovery_actions=["retry_acquisition"],
                    ) from None
                if declared_length is not None and offset + declared_length > max_bytes:
                    raise InstallerError(
                        "ARTIFACT_SIZE_LIMIT_EXCEEDED",
                        "Artifact exceeds the allowed size.",
                        recovery_actions=["obtain_locked_artifact"],
                    )
                mode = "ab" if append else "wb"
                total = offset
                with partial.open(mode) as handle:
                    while True:
                        if cancel_check:
                            cancel_check()
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise InstallerError(
                                "ARTIFACT_SIZE_LIMIT_EXCEEDED",
                                "Artifact exceeds the allowed size.",
                                recovery_actions=["obtain_locked_artifact"],
                            )
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
        except urllib.error.HTTPError as exc:
            if exc.code == 407:
                code = "PROXY_AUTHENTICATION_FAILED"
                retryable = False
            else:
                code = "ARTIFACT_DOWNLOAD_HTTP_FAILED"
                retryable = 500 <= exc.code < 600
            raise InstallerError(
                code,
                "Artifact download failed at the approved HTTPS source.",
                retryable=retryable,
                recovery_actions=["check_proxy_and_network", "retry_acquisition"],
                technical_details={"http_status": exc.code},
            ) from None
        except ssl.SSLError:
            raise InstallerError(
                "TLS_VALIDATION_FAILED",
                "TLS validation failed; certificate checks were not bypassed.",
                recovery_actions=["check_system_trust_and_proxy"],
            ) from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ssl.SSLError):
                raise InstallerError(
                    "TLS_VALIDATION_FAILED",
                    "TLS validation failed; certificate checks were not bypassed.",
                    recovery_actions=["check_system_trust_and_proxy"],
                ) from None
            raise InstallerError(
                "ARTIFACT_DOWNLOAD_INTERRUPTED",
                "Artifact download was interrupted before verification.",
                retryable=True,
                recovery_actions=["check_proxy_and_network", "retry_acquisition"],
                technical_details={"error": type(exc.reason).__name__},
            ) from None
        except (TimeoutError, ConnectionError, OSError) as exc:
            raise InstallerError(
                "ARTIFACT_DOWNLOAD_INTERRUPTED",
                "Artifact download was interrupted before verification.",
                retryable=True,
                recovery_actions=["check_proxy_and_network", "retry_acquisition"],
                technical_details={"error": type(exc).__name__},
            ) from None


def parse_pe_machine(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            header = handle.read(64)
            if len(header) < 64 or header[:2] != b"MZ":
                raise ValueError
            pe_offset = struct.unpack_from("<I", header, 0x3C)[0]
            handle.seek(pe_offset)
            pe_header = handle.read(6)
            if len(pe_header) != 6 or pe_header[:4] != b"PE\0\0":
                raise ValueError
            return struct.unpack_from("<H", pe_header, 4)[0]
    except (OSError, ValueError, struct.error):
        raise InstallerError(
            "ARTIFACT_PE_INVALID",
            "Artifact is not a valid Windows PE executable.",
            recovery_actions=["obtain_locked_artifact"],
        ) from None


def verify_artifact_file(
    path: Path, manifest: ArtifactManifest, *, cancel_check: CancelCheck | None = None
) -> None:
    if not path.is_file():
        raise InstallerError(
            "ARTIFACT_MISSING",
            "Artifact file is missing.",
            retryable=True,
            recovery_actions=["retry_acquisition"],
        )
    size = path.stat().st_size
    if size != manifest.artifact_size:
        raise InstallerError(
            "ARTIFACT_SIZE_MISMATCH",
            "Artifact size does not match the locked manifest.",
            recovery_actions=["discard_artifact", "retry_acquisition"],
            technical_details={"expected_size": manifest.artifact_size, "actual_size": size},
        )
    digest = sha256_file(path, cancel_check=cancel_check)
    if digest != manifest.artifact_sha256:
        raise InstallerError(
            "ARTIFACT_SHA256_MISMATCH",
            "Artifact SHA256 does not match; activation was blocked.",
            recovery_actions=["discard_artifact", "retry_acquisition"],
        )
    if parse_pe_machine(path) != 0x8664:
        raise InstallerError(
            "ARTIFACT_ARCHITECTURE_MISMATCH",
            "Artifact PE architecture is not Windows AMD64.",
            recovery_actions=["obtain_windows_amd64_artifact"],
        )


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in children:
            child.kill()
        if process.poll() is None:
            parent.kill()
        psutil.wait_procs([*children, parent], timeout=3)
    except (psutil.Error, OSError):
        if process.poll() is None:
            process.kill()


def run_isolated_version_probe(
    artifact_path: Path,
    manifest: ArtifactManifest,
    *,
    work_parent: Path,
    cancel_check: CancelCheck | None = None,
) -> str:
    if sys.platform != "win32":
        raise InstallerError(
            "HEALTH_PROBE_PLATFORM_UNSUPPORTED",
            "Windows artifact health probe requires a Windows host.",
            recovery_actions=["run_on_windows"],
        )
    work_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cc-connect-probe-", dir=work_parent) as temp_name:
        isolated = Path(temp_name)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_probe:
            port_probe.bind(("127.0.0.1", 0))
            health_port = int(port_probe.getsockname()[1])
        synthetic_home = isolated / ".cc-connect"
        synthetic_home.mkdir(parents=True)
        (synthetic_home / "config.toml").write_text(
            f'# Synthetic offline health-probe configuration.\nbind = "127.0.0.1:{health_port}"\n',
            encoding="utf-8",
        )
        safe_env = {
            "SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
            "WINDIR": os.environ.get("WINDIR", r"C:\Windows"),
            "PATH": os.environ.get("SystemRoot", r"C:\Windows") + r"\System32",
            "PATHEXT": ".COM;.EXE;.BAT;.CMD",
            "HOME": str(isolated),
            "USERPROFILE": str(isolated),
            "LOCALAPPDATA": str(isolated / "LocalAppData"),
            "APPDATA": str(isolated / "AppData"),
            "TEMP": str(isolated / "Temp"),
            "TMP": str(isolated / "Temp"),
            "NO_PROXY": "*",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "ALL_PROXY": "",
            "CC_CONNECT_HEALTH_PORT": str(health_port),
            "CC_CONNECT_HEALTH_MODE": "version-only-offline",
        }
        (isolated / "Temp").mkdir(parents=True)
        process = subprocess.Popen(
            [str(artifact_path), "--version"],
            cwd=isolated,
            env=safe_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP,
            shell=False,
        )
        deadline = time.monotonic() + 10
        while True:
            try:
                if cancel_check:
                    cancel_check()
                stdout, stderr = process.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    _terminate_process_tree(process)
                    raise InstallerError(
                        "HEALTH_PROBE_TIMEOUT",
                        "Isolated version probe did not exit within the timeout.",
                        retryable=True,
                        recovery_actions=["retry_health_probe"],
                    ) from None
            except InstallerError:
                _terminate_process_tree(process)
                raise
        if process.returncode != 0:
            _terminate_process_tree(process)
            raise InstallerError(
                "HEALTH_PROBE_FAILED",
                "Isolated version probe returned a failure exit code.",
                retryable=True,
                recovery_actions=["inspect_artifact", "retry_health_probe"],
                technical_details={"exit_code": process.returncode},
            )
        output = (stdout or stderr).decode("utf-8", errors="replace")[:4096]
        if manifest.version not in output or manifest.source_commit[:7] not in output:
            raise InstallerError(
                "HEALTH_PROBE_VERSION_MISMATCH",
                "Artifact version output does not match the locked manifest.",
                recovery_actions=["obtain_locked_artifact"],
            )
        return output


def copy_locked_bundle(
    source_dir: Path,
    destination_dir: Path,
    *,
    cancel_check: CancelCheck | None = None,
) -> tuple[ArtifactManifest, bytes]:
    source_root = source_dir.resolve(strict=True)
    manifest_path = source_root / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise InstallerError(
            "MANIFEST_UNAVAILABLE",
            "Trusted artifact manifest is missing.",
            recovery_actions=["configure_ci_artifact_bundle"],
        )
    if manifest_path.is_symlink() or not manifest_path.resolve(strict=True).is_relative_to(
        source_root
    ):
        raise InstallerError(
            "TRUSTED_ARTIFACT_PATH_UNSAFE",
            "Trusted manifest path escapes the configured bundle.",
            recovery_actions=["configure_ci_artifact_bundle"],
        )
    manifest, raw = load_manifest(manifest_path)
    artifact_source = source_root / manifest.artifact_filename
    if not artifact_source.is_file():
        verify_artifact_file(artifact_source, manifest)
    if artifact_source.is_symlink() or not artifact_source.resolve(strict=True).is_relative_to(
        source_root
    ):
        raise InstallerError(
            "TRUSTED_ARTIFACT_PATH_UNSAFE",
            "Trusted artifact path escapes the configured bundle.",
            recovery_actions=["configure_ci_artifact_bundle"],
        )
    verify_artifact_file(artifact_source, manifest, cancel_check=cancel_check)
    destination_is_junction = getattr(destination_dir, "is_junction", lambda: False)
    if destination_dir.exists() and (destination_dir.is_symlink() or destination_is_junction()):
        raise InstallerError(
            "INSTALL_PATH_UNSAFE",
            "Artifact staging directory cannot be a symbolic link.",
            recovery_actions=["inspect_product_state"],
        )
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / manifest.artifact_filename
    partial = destination.with_name(destination.name + ".part")
    with artifact_source.open("rb") as source, partial.open("wb") as target:
        while True:
            if cancel_check:
                cancel_check()
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            target.write(chunk)
        target.flush()
        os.fsync(target.fileno())
    os.replace(partial, destination)
    (destination_dir / MANIFEST_FILENAME).write_bytes(raw)
    verify_artifact_file(destination, manifest, cancel_check=cancel_check)
    return manifest, raw

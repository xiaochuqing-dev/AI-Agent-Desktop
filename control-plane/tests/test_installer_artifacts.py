from __future__ import annotations

import json
import ssl
import urllib.error

import pytest

from control_plane.installer.artifacts import (
    ArtifactDownloader,
    InstallerError,
    _ValidatedRedirectHandler,
    load_manifest_bytes,
    validate_download_url,
    verify_artifact_file,
)

from .installer_helpers import make_pe, manifest_payload, write_test_bundle


def assert_code(expected: str, call) -> None:
    with pytest.raises(InstallerError) as captured:
        call()
    assert captured.value.code == expected


def test_manifest_rejects_lock_mismatch_and_duplicate_keys():
    artifact = make_pe()
    payload = manifest_payload(artifact)
    payload["source_commit"] = "0" * 40
    assert_code(
        "MANIFEST_LOCK_MISMATCH",
        lambda: load_manifest_bytes(json.dumps(payload).encode()),
    )
    assert_code(
        "MANIFEST_INVALID",
        lambda: load_manifest_bytes(b'{"schema_version":"1.0","schema_version":"2.0"}'),
    )


def test_manifest_rejects_unlocked_artifact_digest_and_size():
    payload = manifest_payload(make_pe())
    assert_code(
        "MANIFEST_LOCK_MISMATCH",
        lambda: load_manifest_bytes(json.dumps(payload).encode()),
    )


def test_sha256_mismatch_never_verifies(tmp_path):
    bundle, manifest = write_test_bundle(tmp_path)
    artifact = bundle / manifest.artifact_filename
    artifact.write_bytes(artifact.read_bytes()[:-1] + b"x")
    assert_code("ARTIFACT_SHA256_MISMATCH", lambda: verify_artifact_file(artifact, manifest))


def test_wrong_pe_architecture_is_rejected(tmp_path):
    artifact = make_pe(machine=0x14C)
    bundle, manifest = write_test_bundle(tmp_path, artifact=artifact)
    assert_code(
        "ARTIFACT_ARCHITECTURE_MISMATCH",
        lambda: verify_artifact_file(bundle / manifest.artifact_filename, manifest),
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/release/cc-connect.exe",
        "https://user:password@github.com/release/cc-connect.exe",
        "https://github.com/release/cc-connect.exe?token=secret",
        "https://evil.example/release/cc-connect.exe",
    ],
)
def test_download_url_policy_rejects_unsafe_sources(url):
    assert_code("DOWNLOAD_URL_NOT_ALLOWED", lambda: validate_download_url(url, ("github.com",)))


def test_redirect_policy_validates_every_destination():
    handler = _ValidatedRedirectHandler(("github.com",))
    assert_code(
        "DOWNLOAD_URL_NOT_ALLOWED",
        lambda: handler.redirect_request(None, None, 302, "", {}, "https://evil.example/file"),
    )


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (urllib.error.URLError(ssl.SSLError("certificate failed")), "TLS_VALIDATION_FAILED"),
        (urllib.error.URLError(ConnectionResetError()), "ARTIFACT_DOWNLOAD_INTERRUPTED"),
        (
            urllib.error.HTTPError("https://github.com/a", 407, "proxy", {}, None),
            "PROXY_AUTHENTICATION_FAILED",
        ),
    ],
)
def test_download_failures_have_stable_diagnostics(tmp_path, error, code):
    class FailingOpener:
        def open(self, request, timeout):
            raise error

    downloader = ArtifactDownloader(allowed_hosts=("github.com",), timeout_seconds=1, retries=1)
    downloader._opener = FailingOpener()
    assert_code(
        code,
        lambda: downloader.download("https://github.com/a", tmp_path / "artifact", max_bytes=1024),
    )


def test_interrupted_download_resumes_from_partial_file(tmp_path):
    destination = tmp_path / "artifact"
    partial = tmp_path / "artifact.part"
    partial.write_bytes(b"abc")

    class Response:
        headers = {"Content-Length": "3"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 206

        def geturl(self):
            return "https://github.com/a"

        def read(self, _size):
            value, self.value = getattr(self, "value", b"def"), b""
            return value

    class ResumeOpener:
        def open(self, request, timeout):
            assert request.headers["Range"] == "bytes=3-"
            return Response()

    downloader = ArtifactDownloader(allowed_hosts=("github.com",), timeout_seconds=1, retries=1)
    downloader._opener = ResumeOpener()
    assert (
        downloader.download("https://github.com/a", destination, max_bytes=1024).read_bytes()
        == b"abcdef"
    )
    assert not partial.exists()


def test_size_limit_stops_download_before_write(tmp_path):
    class OversizeResponse:
        headers = {"Content-Length": "2048"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return 200

        def geturl(self):
            return "https://github.com/a"

    class Opener:
        def open(self, request, timeout):
            return OversizeResponse()

    downloader = ArtifactDownloader(allowed_hosts=("github.com",), timeout_seconds=1, retries=1)
    downloader._opener = Opener()
    assert_code(
        "ARTIFACT_SIZE_LIMIT_EXCEEDED",
        lambda: downloader.download("https://github.com/a", tmp_path / "artifact", max_bytes=1024),
    )

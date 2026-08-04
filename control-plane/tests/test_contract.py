import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONTRACTS = os.path.join(REPO_ROOT, "contracts", "control-plane-v1")
VALIDATION_SCRIPT = Path(REPO_ROOT) / "control-plane" / "scripts" / "validate_contracts.py"


def test_core_models_has_new_models():
    with open(os.path.join(CONTRACTS, "core-models.schema.json"), encoding="utf-8") as f:
        m = json.load(f)
    for name in [
        "ReadinessReport",
        "DryRunPlan",
        "DryRunAction",
        "SecretRef",
        "ArtifactManifest",
        "InstallPlan",
        "InstallSnapshot",
        "ManagedVersion",
        "OperationAuditEvent",
    ]:
        assert name in m["$defs"], f"缺少模型 {name}"
    oneof = [r["$ref"].split("/")[-1] for r in m["oneOf"]]
    for name in [
        "ReadinessReport",
        "DryRunPlan",
        "SecretRef",
        "ArtifactManifest",
        "InstallPlan",
        "InstallSnapshot",
        "ManagedVersion",
        "OperationAuditEvent",
    ]:
        assert name in oneof


def test_openapi_frozen_with_readiness_and_events():
    import yaml

    with open(os.path.join(CONTRACTS, "control-plane.openapi.yaml"), encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    assert doc["info"]["version"] == "1.0.0"
    assert doc["info"]["x-contract-status"] == "frozen"
    assert "/readiness" in doc["paths"]
    for path in [
        "/components/{componentId}/install-plan",
        "/components/{componentId}:uninstall",
        "/components/{componentId}:restore",
        "/components/{componentId}/managed-versions",
        "/components/{componentId}/configuration-plans",
        "/components/{componentId}/configuration:apply",
        "/components/{componentId}/ownership-plans",
        "/components/{componentId}/ownership:confirm",
        "/components/{componentId}/lifecycle",
        "/components/{componentId}:reconcile",
        "/components/{componentId}/process-identity",
        "/components/{componentId}/port-ownership",
        "/external-tools/cc-switch",
        "/components/cc-connect/update-assessment",
        "/operations/{operationId}/events",
    ]:
        assert path in doc["paths"]
    event_types = doc["info"]["x-event-types"]
    for t in [
        "com.aiagentdesktop.operation.started.v1",
        "com.aiagentdesktop.operation.failed.v1",
        "com.aiagentdesktop.scan.progress.v1",
        "com.aiagentdesktop.component.discovered.v1",
        "com.aiagentdesktop.plan.generated.v1",
    ]:
        assert t in event_types


def test_event_envelope_pattern_allows_new_types():
    with open(os.path.join(CONTRACTS, "event-envelope.schema.json"), encoding="utf-8") as f:
        m = json.load(f)
    pat = m["properties"]["type"]["pattern"]
    import re

    assert re.match(pat, "com.aiagentdesktop.scan.progress.v1")
    assert re.match(pat, "com.aiagentdesktop.plan.generated.v1")


def test_managed_runtime_schema_has_non_secret_lifecycle_models():
    with open(os.path.join(CONTRACTS, "managed-runtime.schema.json"), encoding="utf-8") as f:
        models = json.load(f)
    for name in [
        "ManagedConfiguration",
        "ConfigurationPlan",
        "OwnershipPlan",
        "ProcessIdentity",
        "PortOwnershipEvidence",
        "LifecycleRuntimeStatus",
        "UpdateAssessment",
        "ExternalToolStatus",
    ]:
        assert name in models["$defs"]
    configuration = models["$defs"]["ManagedConfiguration"]
    assert "token" not in configuration["properties"]
    assert "api_key" not in configuration["properties"]


def test_contract_validation_resolves_external_refs_from_any_working_directory(tmp_path):
    result = subprocess.run(
        [sys.executable, str(VALIDATION_SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "control-plane.openapi.yaml" in result.stdout
    assert "core-models.schema.json" in result.stdout
    assert "event-envelope.schema.json" in result.stdout
    assert "managed-runtime.schema.json" in result.stdout

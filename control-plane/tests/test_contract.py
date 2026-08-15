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
        "/credentials/capability",
        "/credentials/telegram",
        "/credentials/telegram/{slot}",
        "/credentials/telegram/{slot}:replace",
        "/telegram/bots",
        "/telegram/bots/{slot}:verify",
        "/telegram/bots/{slot}/webhook",
        "/telegram/bots/{slot}/webhook:delete",
        "/telegram/update-leases",
        "/telegram/bindings",
        "/telegram/bindings/{sessionId}",
        "/telegram/bindings/{sessionId}:resume",
        "/telegram/bindings/{sessionId}:cancel",
        "/telegram/bindings/{sessionId}/slots/{slot}:poll",
        "/components/{componentId}/native-configuration/renderer",
        "/components/{componentId}/native-configuration-plans",
        "/components/{componentId}/native-configuration:apply",
        "/components/{componentId}/native-configuration",
        "/components/{componentId}/external-cc-connect",
        "/components/hermes/telegram-configuration-plans",
        "/components/hermes/telegram-configuration",
        "/components/hermes/telegram-readiness",
        "/components/hermes/telegram-configuration:plan",
        "/components/hermes/telegram-configuration:apply",
        "/observability/links",
        "/observability/links/{linkId}",
        "/observability/links/{linkId}/e2e-plans",
        "/observability/e2e-plans/{planId}",
        "/observability/e2e-plans/{planId}:confirm",
        "/observability/e2e-plans/{planId}:cancel",
        "/observability/e2e-runs",
        "/observability/e2e-runs/{runId}/response",
        "/observability/synthetic-e2e:run",
        "/observability/session-isolation:probe",
        "/observability/session-isolation",
        "/telegram/network-policy",
        "/agents",
        "/onboarding/snapshot",
        "/dashboard/snapshot",
        "/telegram/client-availability",
    ]:
        assert path in doc["paths"]
    assert any(item["name"] == "Onboarding" for item in doc["tags"])
    expected_gui_refs = {
        "/onboarding/snapshot": "./onboarding.schema.json#/$defs/OnboardingSnapshot",
        "/dashboard/snapshot": "./onboarding.schema.json#/$defs/DashboardSnapshot",
        "/telegram/client-availability": "./onboarding.schema.json#/$defs/TelegramClientAvailability",
    }
    for path, expected_ref in expected_gui_refs.items():
        schema = doc["paths"][path]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert schema["$ref"] == expected_ref
    assert any(item["name"] == "Observability" for item in doc["tags"])
    for schema in [
        "AgentDetectionSnapshot",
        "LinkState",
        "E2ETestPlan",
        "E2ETestConfirmation",
        "E2ETestRun",
        "E2ETestResponseEvidence",
        "SessionIsolationResult",
        "ProxyPolicyState",
    ]:
        assert schema in doc["components"]["schemas"]
    resume_schema = doc["components"]["schemas"]["BindingResumeRequest"]
    assert resume_schema["properties"]["runtimes_stopped_confirmation"] == {"const": True}
    problem = doc["components"]["schemas"]["Problem"]
    assert "errors" in problem["properties"]
    assert "secret" not in problem["properties"]
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
        "CredentialMetadata",
        "CredentialBackendCapability",
        "TelegramBotIdentity",
        "TelegramWebhookInfo",
        "TelegramUpdateLease",
        "BindingSession",
        "BindingSessionCreated",
        "NativeRendererCapability",
        "NativeRuntimeConfig",
        "ManagedCcConnectState",
        "NativeConfigurationPlan",
        "NativeConfigurationState",
        "HermesConfigurationPlan",
        "HermesConfigurationState",
        "HermesTelegramReadinessSnapshot",
        "HermesTelegramConfigurationPlanRequest",
        "HermesTelegramConfigurationPlan",
        "HermesTelegramApplyRequest",
        "ExternalCcConnectState",
    ]:
        assert name in models["$defs"]
    configuration = models["$defs"]["ManagedConfiguration"]
    assert "token" not in configuration["properties"]
    assert "api_key" not in configuration["properties"]
    native_runtime = models["$defs"]["NativeRuntimeConfig"]
    assert "token" not in native_runtime["properties"]
    assert "secret" not in native_runtime["properties"]
    health = models["$defs"]["RuntimeHealth"]
    for field in [
        "management_api_verified",
        "management_api_status",
        "management_api_bind_scope",
    ]:
        assert field in health["properties"]

    created = models["$defs"]["BindingSessionCreated"]
    assert "group_deep_links" in created["required"]
    assert "group_deep_links" in created["properties"]


def test_onboarding_schema_has_redacted_gui_snapshots():
    with open(os.path.join(CONTRACTS, "onboarding.schema.json"), encoding="utf-8") as f:
        models = json.load(f)
    for name in [
        "OnboardingSnapshot",
        "DashboardSnapshot",
        "TelegramClientAvailability",
    ]:
        assert name in models["$defs"]
    assert (
        models["$defs"]["OnboardingSnapshot"]["properties"]["telegram_client"]["$ref"]
        == "#/$defs/TelegramClientAvailability"
    )
    serialized = json.dumps(models).lower()
    assert '"token"' not in serialized
    assert '"bind_code"' not in serialized
    assert '"message_body"' not in serialized


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
    assert "onboarding.schema.json" in result.stdout

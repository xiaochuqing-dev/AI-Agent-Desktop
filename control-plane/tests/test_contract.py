import json
import os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONTRACTS = os.path.join(REPO_ROOT, "contracts", "control-plane-v1")


def test_core_models_has_new_models():
    with open(os.path.join(CONTRACTS, "core-models.schema.json"), encoding="utf-8") as f:
        m = json.load(f)
    for name in ["ReadinessReport", "DryRunPlan", "DryRunAction", "SecretRef"]:
        assert name in m["$defs"], f"缺少模型 {name}"
    oneof = [r["$ref"].split("/")[-1] for r in m["oneOf"]]
    for name in ["ReadinessReport", "DryRunPlan", "SecretRef"]:
        assert name in oneof


def test_openapi_frozen_with_readiness_and_events():
    import yaml

    with open(os.path.join(CONTRACTS, "control-plane.openapi.yaml"), encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    assert doc["info"]["version"] == "1.0.0"
    assert doc["info"]["x-contract-status"] == "frozen"
    assert "/readiness" in doc["paths"]
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

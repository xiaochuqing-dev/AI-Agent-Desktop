"""Validate the frozen Control Plane v1 machine-readable contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema.validators import validator_for
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_DIRECTORY = Path("contracts") / "control-plane-v1"
OPENAPI_FILENAME = "control-plane.openapi.yaml"
JSON_SCHEMA_FILENAMES = ("core-models.schema.json", "event-envelope.schema.json")


def _validate_json_schema(path: Path) -> None:
    with path.open(encoding="utf-8") as stream:
        schema: dict[str, Any] = json.load(stream)
    validator = validator_for(schema)
    validator.check_schema(schema)


def validate_contracts(repo_root: Path = REPO_ROOT) -> list[Path]:
    """Validate OpenAPI external refs and both JSON Schemas from any cwd."""
    contract_dir = repo_root.resolve() / CONTRACT_DIRECTORY
    openapi_path = contract_dir / OPENAPI_FILENAME

    spec, base_uri = read_from_filename(str(openapi_path))
    validate(spec, base_uri=base_uri)

    validated = [openapi_path]
    for filename in JSON_SCHEMA_FILENAMES:
        schema_path = contract_dir / filename
        _validate_json_schema(schema_path)
        validated.append(schema_path)
    return validated


def main() -> None:
    validated = validate_contracts()
    for path in validated:
        print(f"validated: {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

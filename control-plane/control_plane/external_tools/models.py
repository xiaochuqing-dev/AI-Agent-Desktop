from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExternalToolCapability(StrictModel):
    capability: Literal[
        "detection",
        "launch",
        "supported_agents",
        "install",
        "update",
        "configuration",
        "ownership_handoff",
    ]
    status: Literal["supported", "unavailable", "unknown"]
    evidence: str


class ExternalToolStatus(StrictModel):
    provider_id: str
    display_name: str
    installation_status: Literal["installed", "not_installed", "unknown"]
    executable_path: str | None = None
    version: str | None = None
    supported_agents: list[str] = Field(default_factory=list)
    capabilities: list[ExternalToolCapability]
    lifecycle_owner: Literal["external"] = "external"
    management_owner: Literal["external"] = "external"
    last_verified_at: datetime
    evidence: dict[str, Any] = Field(default_factory=dict)


class ExternalToolProvider(Protocol):
    provider_id: str

    def detect(self) -> ExternalToolStatus: ...

    def launch(self) -> dict[str, Any]: ...

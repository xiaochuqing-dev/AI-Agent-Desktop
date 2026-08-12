from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

AgentId = Literal["hermes", "claude", "codex"]


class DetectionStatus(StrEnum):
    INSTALLED = "installed"
    NOT_FOUND = "not_found"
    FOUND_BUT_UNHEALTHY = "found_but_unhealthy"
    VERSION_UNKNOWN = "version_unknown"
    DETECTION_ERROR = "detection_error"


class ProbeStatus(StrEnum):
    NOT_RUN = "not_run"
    HEALTHY = "healthy"
    VERSION_UNKNOWN = "version_unknown"
    FAILED = "failed"
    TIMEOUT = "timeout"
    LAUNCH_ERROR = "launch_error"


class DetectionSource(StrEnum):
    PATH = "path"
    KNOWN_LOCATION = "known_location"
    NOT_FOUND = "not_found"
    ERROR = "error"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentDetectionResult(StrictModel):
    agent_id: AgentId
    display_name: str
    status: DetectionStatus
    installed: bool | None
    version: str | None = None
    executable_path_internal: str | None = None
    detection_source: DetectionSource
    probe_status: ProbeStatus
    probe_exit_code: int | None = None
    observed_at: datetime
    diagnostic_code: str | None = None
    user_message: str
    official_install_url: str
    revision: str

    @property
    def acceptable(self) -> bool:
        return bool(
            self.installed
            and self.status in {DetectionStatus.INSTALLED, DetectionStatus.VERSION_UNKNOWN}
            and self.probe_status in {ProbeStatus.HEALTHY, ProbeStatus.VERSION_UNKNOWN}
        )

    def public_snapshot(self) -> AgentDetectionSnapshot:
        return AgentDetectionSnapshot(
            agent_id=self.agent_id,
            display_name=self.display_name,
            status=self.status,
            installed=self.installed,
            version=self.version,
            detection_source=self.detection_source,
            probe_status=self.probe_status,
            observed_at=self.observed_at,
            diagnostic_code=self.diagnostic_code,
            user_message=self.user_message,
            official_install_url=self.official_install_url,
            acceptable=self.acceptable,
            revision=self.revision,
        )


class AgentDetectionSnapshot(StrictModel):
    """Redacted Agent detection contract; executable paths never leave the service."""

    agent_id: AgentId
    display_name: str
    status: DetectionStatus
    installed: bool | None
    version: str | None = None
    detection_source: DetectionSource
    probe_status: ProbeStatus
    observed_at: datetime
    diagnostic_code: str | None = None
    user_message: str
    official_install_url: str
    acceptable: bool
    revision: str

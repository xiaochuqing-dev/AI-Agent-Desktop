from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HermesConfigurationPlanRequest(StrictModel):
    binding_session_id: str = Field(min_length=1, max_length=128)


class HermesConfigurationPlan(StrictModel):
    plan_id: str
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    binding_session_id: str
    status: Literal["plan_ready_external_owner", "pending_component_install"]
    installed: bool
    management_owner: Literal["external", "unknown"]
    credential_reference_id: Literal["telegram/hermes-bot-token"] = "telegram/hermes-bot-token"
    token_environment_variable: Literal["TELEGRAM_BOT_TOKEN"] = "TELEGRAM_BOT_TOKEN"
    non_secret_environment: dict[str, str]
    writes_external_configuration: Literal[False] = False
    apply_supported: Literal[False] = False
    reason: str
    created_at: datetime


class HermesConfigurationState(StrictModel):
    status: Literal["missing_plan", "plan_ready_external_owner", "pending_component_install"]
    latest_plan: HermesConfigurationPlan | None = None

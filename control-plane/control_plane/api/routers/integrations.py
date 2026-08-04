from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from ...security.redaction import redact_value
from ...updates.models import UpdateChannel, VersionPolicy


class LaunchConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: Literal[True]


def build_integrations_router(
    get_state: Callable[[], Any], bearer_auth: Callable[..., str]
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Integrations"])

    @router.get("/external-tools/cc-switch")
    def cc_switch_status(_token: str = Depends(bearer_auth)):
        return redact_value(get_state().cc_switch.detect().model_dump(mode="json"))

    @router.post("/external-tools/cc-switch:launch")
    def launch_cc_switch(
        payload: LaunchConfirmation,
        _token: str = Depends(bearer_auth),
    ):
        assert payload.confirmation
        return redact_value(get_state().cc_switch.launch())

    @router.get("/components/cc-connect/update-assessment")
    def cc_connect_update_assessment(
        requested_version: str = Query(min_length=1, max_length=128),
        _token: str = Depends(bearer_auth),
    ):
        policy = VersionPolicy(
            channel=UpdateChannel.EXACT,
            requested_version=requested_version,
        )
        return redact_value(get_state().cc_connect_updates.assess(policy).model_dump(mode="json"))

    @router.get("/components/hermes/update-assessment")
    def hermes_update_assessment(
        requested_version: str = Query(min_length=1, max_length=128),
        _token: str = Depends(bearer_auth),
    ):
        policy = VersionPolicy(
            channel=UpdateChannel.EXACT,
            requested_version=requested_version,
        )
        return redact_value(get_state().hermes_updates.assess(policy).model_dump(mode="json"))

    return router

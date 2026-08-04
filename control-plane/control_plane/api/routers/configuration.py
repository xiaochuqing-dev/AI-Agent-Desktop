from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, Request, Response

from ...configuration.models import (
    ConfigurationConfirmationRequest,
    ConfigurationPlan,
    ConfigurationPlanRequest,
    ConfigurationState,
)
from ...installer.artifacts import InstallerError
from ...security.redaction import redact_value
from ..errors import capability_unsupported


def build_configuration_router(
    get_state: Callable[[], Any], bearer_auth: Callable[..., str]
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Configuration"])

    def require_component(component_id: str) -> None:
        if component_id != "cc-connect":
            raise capability_unsupported(component_id, "configuration")

    @router.post(
        "/components/{component_id}/configuration-plans",
        response_model=ConfigurationPlan,
        status_code=201,
    )
    def create_plan(
        component_id: str,
        payload: ConfigurationPlanRequest,
        _token: str = Depends(bearer_auth),
    ):
        require_component(component_id)
        plan = get_state().configuration.create_plan(payload)
        return redact_value(plan.model_dump(mode="json"))

    @router.get(
        "/components/{component_id}/configuration-plans/{plan_id}",
        response_model=ConfigurationPlan,
    )
    def get_plan(
        component_id: str,
        plan_id: str,
        _token: str = Depends(bearer_auth),
    ):
        require_component(component_id)
        plan = get_state().configuration.get_plan(plan_id)
        if plan is None:
            raise InstallerError(
                "CONFIGURATION_PLAN_NOT_FOUND",
                "Configuration plan was not found.",
                recovery_actions=["create_configuration_plan"],
            )
        return redact_value(plan.model_dump(mode="json"))

    @router.post(
        "/components/{component_id}/configuration:apply",
        status_code=202,
    )
    async def apply_plan(
        component_id: str,
        payload: ConfigurationConfirmationRequest,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(bearer_auth),
    ):
        require_component(component_id)
        state = get_state()
        operation, reused = state.configuration.confirm_plan(
            payload,
            idempotency_key=idempotency_key,
            body=await request.body(),
        )
        if not reused:
            state.executor.submit(
                operation_id=operation.operation_id,
                component_id=component_id,
                kind="cc_connect_configuration_apply",
                payload={"plan_id": payload.plan_id},
            )
        response.headers["Location"] = f"/api/v1/operations/{operation.operation_id}"
        return redact_value(operation.model_dump(mode="json"))

    @router.get(
        "/components/{component_id}/configuration",
        response_model=ConfigurationState,
    )
    def configuration_state(
        component_id: str,
        _token: str = Depends(bearer_auth),
    ):
        require_component(component_id)
        return redact_value(get_state().configuration.state().model_dump(mode="json"))

    return router

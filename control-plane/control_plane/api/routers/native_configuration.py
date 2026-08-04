from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Header, Request, Response

from ...cc_connect.native_config_models import (
    NativeConfigurationConfirmation,
    NativeConfigurationPlan,
    NativeConfigurationPlanRequest,
    NativeConfigurationState,
    NativeRendererCapability,
)
from ...hermes.models import (
    HermesConfigurationPlan,
    HermesConfigurationPlanRequest,
    HermesConfigurationState,
)
from ...installer.artifacts import InstallerError
from ...security.redaction import redact_value
from ..errors import capability_unsupported


def build_native_configuration_router(
    get_state: Callable[[], Any], bearer_auth: Callable[..., str]
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Native Configuration"])

    def require_cc_connect(component_id: str) -> None:
        if component_id != "cc-connect":
            raise capability_unsupported(component_id, "native-configuration")

    @router.get(
        "/components/{component_id}/native-configuration/renderer",
        response_model=NativeRendererCapability,
    )
    def renderer_capability(
        component_id: str,
        _token: str = Depends(bearer_auth),
    ):
        require_cc_connect(component_id)
        return redact_value(get_state().native_configuration.capability().model_dump(mode="json"))

    @router.post(
        "/components/{component_id}/native-configuration-plans",
        response_model=NativeConfigurationPlan,
        status_code=201,
    )
    def create_plan(
        component_id: str,
        payload: NativeConfigurationPlanRequest,
        _token: str = Depends(bearer_auth),
    ):
        require_cc_connect(component_id)
        return redact_value(
            get_state().native_configuration.create_plan(payload).model_dump(mode="json")
        )

    @router.get(
        "/components/{component_id}/native-configuration-plans/{plan_id}",
        response_model=NativeConfigurationPlan,
    )
    def get_plan(
        component_id: str,
        plan_id: str,
        _token: str = Depends(bearer_auth),
    ):
        require_cc_connect(component_id)
        plan = get_state().native_configuration.get_plan(plan_id)
        if plan is None:
            raise InstallerError(
                "NATIVE_CONFIGURATION_PLAN_NOT_FOUND",
                "Native configuration plan was not found.",
                recovery_actions=["create_native_configuration_plan"],
            )
        return redact_value(plan.model_dump(mode="json"))

    @router.post(
        "/components/{component_id}/native-configuration:apply",
        status_code=202,
    )
    async def apply_plan(
        component_id: str,
        payload: NativeConfigurationConfirmation,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(bearer_auth),
    ):
        require_cc_connect(component_id)
        state = get_state()
        operation, reused = state.native_configuration.confirm_plan(
            payload,
            idempotency_key=idempotency_key,
            body=await request.body(),
        )
        if not reused:
            state.executor.submit(
                operation_id=operation.operation_id,
                component_id=component_id,
                kind="cc_connect_native_configuration_apply",
                payload={"plan_id": payload.plan_id},
            )
        response.headers["Location"] = f"/api/v1/operations/{operation.operation_id}"
        return redact_value(operation.model_dump(mode="json"))

    @router.get(
        "/components/{component_id}/native-configuration",
        response_model=NativeConfigurationState,
    )
    def native_state(component_id: str, _token: str = Depends(bearer_auth)):
        require_cc_connect(component_id)
        return redact_value(get_state().native_configuration.state().model_dump(mode="json"))

    @router.get("/components/{component_id}/external-cc-connect")
    def external_state(component_id: str, _token: str = Depends(bearer_auth)):
        require_cc_connect(component_id)
        native = get_state().native_configuration.state()
        port = native.runtime_config.management_port if native.runtime_config else None
        path = get_state().native_configuration.store.runtime_path
        return redact_value(
            get_state()
            .cc_connect_external.detect(
                target_port=port,
                target_config_path=path,
            )
            .model_dump(mode="json")
        )

    @router.post(
        "/components/hermes/telegram-configuration-plans",
        response_model=HermesConfigurationPlan,
        status_code=201,
    )
    def create_hermes_plan(
        payload: HermesConfigurationPlanRequest,
        _token: str = Depends(bearer_auth),
    ):
        return redact_value(
            get_state().hermes_configuration.create_plan(payload).model_dump(mode="json")
        )

    @router.get(
        "/components/hermes/telegram-configuration",
        response_model=HermesConfigurationState,
    )
    def hermes_state(_token: str = Depends(bearer_auth)):
        return redact_value(get_state().hermes_configuration.state().model_dump(mode="json"))

    return router

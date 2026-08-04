from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Request, Response

from ...installer.artifacts import InstallerError
from ...lifecycle.models import (
    LifecycleActionRequest,
    LifecycleRuntimeStatus,
    OwnershipConfirmationRequest,
    OwnershipPlan,
    OwnershipPlanRequest,
)
from ...security.redaction import redact_value
from ..errors import capability_unsupported


def build_lifecycle_router(
    get_state: Callable[[], Any], bearer_auth: Callable[..., str]
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["Lifecycle"])

    def require_component(component_id: str) -> None:
        if component_id != "cc-connect":
            raise capability_unsupported(component_id, "managed-lifecycle")

    @router.post(
        "/components/{component_id}/ownership-plans",
        response_model=OwnershipPlan,
        status_code=201,
    )
    def create_ownership_plan(
        component_id: str,
        payload: OwnershipPlanRequest,
        _token: str = Depends(bearer_auth),
    ):
        require_component(component_id)
        plan = get_state().lifecycle.create_ownership_plan(payload)
        return redact_value(plan.model_dump(mode="json"))

    @router.get(
        "/components/{component_id}/ownership-plans/{plan_id}",
        response_model=OwnershipPlan,
    )
    def get_ownership_plan(
        component_id: str,
        plan_id: str,
        _token: str = Depends(bearer_auth),
    ):
        require_component(component_id)
        plan = get_state().lifecycle.get_ownership_plan(plan_id)
        if plan is None:
            raise InstallerError(
                "OWNERSHIP_PLAN_NOT_FOUND",
                "Lifecycle ownership plan was not found.",
                recovery_actions=["create_ownership_handoff_plan"],
            )
        return redact_value(plan.model_dump(mode="json"))

    @router.post(
        "/components/{component_id}/ownership:confirm",
        status_code=202,
    )
    async def confirm_ownership_plan(
        component_id: str,
        payload: OwnershipConfirmationRequest,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(bearer_auth),
    ):
        require_component(component_id)
        state = get_state()
        operation, reused = state.lifecycle.confirm_ownership_plan(
            payload,
            idempotency_key=idempotency_key,
            body=await request.body(),
        )
        if not reused:
            state.executor.submit(
                operation_id=operation.operation_id,
                component_id=component_id,
                kind="cc_connect_ownership_handoff",
                payload={"action": "ownership_handoff", "plan_id": payload.plan_id},
            )
        response.headers["Location"] = f"/api/v1/operations/{operation.operation_id}"
        return redact_value(operation.model_dump(mode="json"))

    async def create_lifecycle_operation(
        action: Literal["start", "stop", "restart", "reconcile", "health"],
        component_id: str,
        payload: LifecycleActionRequest,
        request: Request,
        response: Response,
        idempotency_key: str,
    ):
        require_component(component_id)
        state = get_state()
        operation, reused = state.lifecycle.create_operation(
            action,
            payload,
            idempotency_key=idempotency_key,
            body=await request.body(),
        )
        if not reused:
            state.executor.submit(
                operation_id=operation.operation_id,
                component_id=component_id,
                kind=f"cc_connect_lifecycle_{action}",
                payload={"action": action, "request": payload.model_dump(mode="json")},
            )
        response.headers["Location"] = f"/api/v1/operations/{operation.operation_id}"
        return redact_value(operation.model_dump(mode="json"))

    @router.post("/components/{component_id}:start", status_code=202)
    async def start(
        component_id: str,
        payload: LifecycleActionRequest,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(bearer_auth),
    ):
        return await create_lifecycle_operation(
            "start", component_id, payload, request, response, idempotency_key
        )

    @router.post("/components/{component_id}:stop", status_code=202)
    async def stop(
        component_id: str,
        payload: LifecycleActionRequest,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(bearer_auth),
    ):
        return await create_lifecycle_operation(
            "stop", component_id, payload, request, response, idempotency_key
        )

    @router.post("/components/{component_id}:restart", status_code=202)
    async def restart(
        component_id: str,
        payload: LifecycleActionRequest,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(bearer_auth),
    ):
        return await create_lifecycle_operation(
            "restart", component_id, payload, request, response, idempotency_key
        )

    @router.post("/components/{component_id}:reconcile", status_code=202)
    async def reconcile(
        component_id: str,
        payload: LifecycleActionRequest,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(bearer_auth),
    ):
        return await create_lifecycle_operation(
            "reconcile", component_id, payload, request, response, idempotency_key
        )

    @router.post("/components/{component_id}/health:check", status_code=202)
    async def health_check(
        component_id: str,
        payload: LifecycleActionRequest,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(bearer_auth),
    ):
        return await create_lifecycle_operation(
            "health", component_id, payload, request, response, idempotency_key
        )

    @router.get(
        "/components/{component_id}/lifecycle",
        response_model=LifecycleRuntimeStatus,
    )
    def status(component_id: str, _token: str = Depends(bearer_auth)):
        require_component(component_id)
        return redact_value(get_state().lifecycle.status().model_dump(mode="json"))

    @router.get("/components/{component_id}/health")
    def health(component_id: str, _token: str = Depends(bearer_auth)):
        require_component(component_id)
        return redact_value(get_state().lifecycle.status().health.model_dump(mode="json"))

    @router.get("/components/{component_id}/process-identity")
    def process_identity(component_id: str, _token: str = Depends(bearer_auth)):
        require_component(component_id)
        status = get_state().lifecycle.status()
        return redact_value(
            {
                "identity": status.identity.model_dump(mode="json") if status.identity else None,
                "verification": (
                    status.identity_verification.model_dump(mode="json")
                    if status.identity_verification
                    else None
                ),
            }
        )

    @router.get("/components/{component_id}/port-ownership")
    def port_ownership(component_id: str, _token: str = Depends(bearer_auth)):
        require_component(component_id)
        status = get_state().lifecycle.status()
        return redact_value(
            status.port_ownership.model_dump(mode="json") if status.port_ownership else None
        )

    @router.get("/components/{component_id}/owners")
    def owners(component_id: str, _token: str = Depends(bearer_auth)):
        require_component(component_id)
        management, lifecycle = get_state().configuration.owners()
        return {"management_owner": management.value, "lifecycle_owner": lifecycle.value}

    return router

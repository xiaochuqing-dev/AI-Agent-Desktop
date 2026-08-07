from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from ...observability.models import (
    E2ETestConfirmation,
    E2ETestPlan,
    E2ETestResponseEvidence,
    E2ETestRun,
    LinkId,
    LinkState,
    SessionIsolationResult,
)
from ...observability.service import ObservabilityError
from ...operations import OperationExecutionError
from ...security.redaction import redact_value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanCreateRequest(StrictModel):
    expires_in_seconds: int = Field(default=300, ge=60, le=900)


class PlanCancelRequest(StrictModel):
    confirmation: Literal[True]


def _call(action):
    try:
        return action()
    except ObservabilityError as exc:
        raise OperationExecutionError(
            exc.code,
            exc.message,
            recovery_actions=exc.recovery_actions,
        ) from None


def build_observability_router(
    get_state: Callable[[], Any], bearer_auth: Callable[..., str]
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/observability", tags=["Observability"])

    @router.get("/links", response_model=list[LinkState])
    def list_links(_token: str = Depends(bearer_auth)):
        return redact_value(
            [item.model_dump(mode="json") for item in get_state().observability.list_links()]
        )

    @router.get("/links/{link_id}", response_model=LinkState)
    def get_link(link_id: LinkId, _token: str = Depends(bearer_auth)):
        return redact_value(get_state().observability.get_link(link_id).model_dump(mode="json"))

    @router.post("/links/{link_id}/e2e-plans", response_model=E2ETestPlan, status_code=201)
    def create_plan(
        link_id: LinkId,
        payload: PlanCreateRequest,
        _token: str = Depends(bearer_auth),
    ):
        plan = _call(
            lambda: get_state().observability.create_plan(
                link_id, expires_in_seconds=payload.expires_in_seconds
            )
        )
        return redact_value(plan.model_dump(mode="json"))

    @router.get("/e2e-plans/{plan_id}", response_model=E2ETestPlan)
    def get_plan(plan_id: str, _token: str = Depends(bearer_auth)):
        plan = get_state().observability.get_plan(plan_id)
        if plan is None:
            raise OperationExecutionError("E2E_PLAN_NOT_FOUND", "E2E plan was not found.")
        return redact_value(plan.model_dump(mode="json"))

    @router.post("/e2e-plans/{plan_id}:confirm", response_model=E2ETestRun)
    def confirm_plan(
        plan_id: str,
        payload: E2ETestConfirmation,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(bearer_auth),
    ):
        if payload.plan_id != plan_id:
            raise OperationExecutionError("E2E_PLAN_ID_MISMATCH", "Path and body plan IDs differ.")
        run = _call(
            lambda: get_state().observability.confirm_plan(payload, idempotency_key=idempotency_key)
        )
        return redact_value(run.model_dump(mode="json"))

    @router.post("/e2e-plans/{plan_id}:cancel", response_model=E2ETestPlan)
    def cancel_plan(
        plan_id: str,
        payload: PlanCancelRequest,
        _token: str = Depends(bearer_auth),
    ):
        plan = _call(
            lambda: get_state().observability.cancel_plan(
                plan_id, confirmation=payload.confirmation
            )
        )
        return redact_value(plan.model_dump(mode="json"))

    @router.get("/e2e-runs", response_model=list[E2ETestRun])
    def list_runs(_token: str = Depends(bearer_auth)):
        return redact_value(
            [item.model_dump(mode="json") for item in get_state().observability.latest_runs()]
        )

    @router.post("/e2e-runs/{run_id}/response", response_model=E2ETestRun)
    def record_response(
        run_id: str,
        payload: E2ETestResponseEvidence,
        _token: str = Depends(bearer_auth),
    ):
        if payload.run_id != run_id:
            raise OperationExecutionError("E2E_RUN_ID_MISMATCH", "Path and body run IDs differ.")
        run = _call(lambda: get_state().observability.record_response(payload))
        return redact_value(run.model_dump(mode="json"))

    @router.post("/synthetic-e2e:run", response_model=list[E2ETestRun])
    def run_synthetic(_token: str = Depends(bearer_auth)):
        return redact_value(
            [item.model_dump(mode="json") for item in get_state().observability.run_synthetic()]
        )

    @router.post("/session-isolation:probe", response_model=SessionIsolationResult)
    def run_isolation_probe(_token: str = Depends(bearer_auth)):
        return redact_value(get_state().observability.isolation.run().model_dump(mode="json"))

    @router.get("/session-isolation", response_model=SessionIsolationResult | None)
    def get_isolation_result(_token: str = Depends(bearer_auth)):
        result = get_state().observability.isolation.latest()
        return redact_value(result.model_dump(mode="json") if result else None)

    return router

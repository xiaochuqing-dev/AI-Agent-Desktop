from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Request, Response

from ...application.operation_store import OperationStore
from ...credentials.models import (
    PUBLIC_CREDENTIAL_REFERENCES,
    CredentialBackendCapability,
    CredentialDeleteRequest,
    CredentialMetadata,
    CredentialMutationRequest,
)
from ...credentials.windows_backend import CredentialBackendError
from ...domain.models import OperationStatus, ResourceRef, UserFacingError
from ...security.redaction import redact_value

Slot = Literal["hermes", "claude", "codex"]


def build_credentials_router(
    get_state: Callable[[], Any], bearer_auth: Callable[..., str]
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/credentials", tags=["Credentials"])

    def reference(slot: Slot) -> str:
        return PUBLIC_CREDENTIAL_REFERENCES[slot][0]

    def start_operation(kind: str, ref: str, key: str, method: str, resource: str, body: bytes):
        state = get_state()
        with state.db.session() as session:
            operation, reused = OperationStore(session).create(
                kind=kind,
                target_ref=ResourceRef(kind="credential", id=ref.replace("/", ":")),
                idempotency_key=key,
                method=method,
                resource=resource,
                body=body,
            )
            if not reused:
                OperationStore(session).transition(
                    operation.operation_id,
                    status=OperationStatus.RUNNING,
                    phase="credential_write",
                    message="Writing a referenced secret to the native credential backend.",
                )
        return operation, reused

    def finish(operation_id: str, metadata: CredentialMetadata) -> None:
        state = get_state()
        with state.db.session() as session:
            OperationStore(session).transition(
                operation_id,
                status=OperationStatus.SUCCEEDED,
                phase="credential_write_completed",
                message="Credential metadata was updated without persisting the secret.",
                result=metadata.model_dump(mode="json"),
            )

    def fail(operation_id: str, error: CredentialBackendError) -> None:
        state = get_state()
        with state.db.session() as session:
            OperationStore(session).transition(
                operation_id,
                status=OperationStatus.FAILED,
                phase="credential_write_failed",
                message=error.message,
                error=UserFacingError(
                    code=error.code,
                    message=error.message,
                    retryable=error.status.value in {"unknown", "backend_unavailable"},
                    recovery_actions=["inspect_credential_backend", "retry_explicitly"],
                ),
            )

    async def mutate(
        action: Literal["put", "replace"],
        slot: Slot,
        payload: CredentialMutationRequest,
        request: Request,
        response: Response,
        idempotency_key: str,
    ) -> CredentialMetadata:
        state = get_state()
        ref = reference(slot)
        resource = f"/api/v1/credentials/telegram/{slot}"
        if action == "replace":
            resource += ":replace"
        operation, reused = start_operation(
            f"credential_{action}",
            ref,
            idempotency_key,
            "PUT" if action == "put" else "POST",
            resource,
            await request.body(),
        )
        response.headers["X-Operation-ID"] = operation.operation_id
        if reused:
            return state.credentials.get(ref)
        try:
            metadata = (
                state.credentials.put(ref, payload.secret, operation_id=operation.operation_id)
                if action == "put"
                else state.credentials.replace(
                    ref, payload.secret, operation_id=operation.operation_id
                )
            )
        except CredentialBackendError as exc:
            fail(operation.operation_id, exc)
            raise
        finish(operation.operation_id, metadata)
        return metadata

    @router.get("/capability", response_model=CredentialBackendCapability)
    def capability(_token: str = Depends(bearer_auth)):
        return redact_value(get_state().credentials.capability().model_dump(mode="json"))

    @router.get("/telegram", response_model=list[CredentialMetadata])
    def list_credentials(_token: str = Depends(bearer_auth)):
        return redact_value(
            [item.model_dump(mode="json") for item in get_state().credentials.list_metadata()]
        )

    @router.get("/telegram/{slot}", response_model=CredentialMetadata)
    def status(slot: Slot, _token: str = Depends(bearer_auth)):
        return redact_value(get_state().credentials.get(reference(slot)).model_dump(mode="json"))

    @router.put("/telegram/{slot}", response_model=CredentialMetadata, status_code=201)
    async def put(
        slot: Slot,
        payload: CredentialMutationRequest,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(bearer_auth),
    ):
        return redact_value(
            (await mutate("put", slot, payload, request, response, idempotency_key)).model_dump(
                mode="json"
            )
        )

    @router.post("/telegram/{slot}:replace", response_model=CredentialMetadata)
    async def replace(
        slot: Slot,
        payload: CredentialMutationRequest,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(bearer_auth),
    ):
        return redact_value(
            (await mutate("replace", slot, payload, request, response, idempotency_key)).model_dump(
                mode="json"
            )
        )

    @router.delete("/telegram/{slot}", response_model=CredentialMetadata)
    async def delete(
        slot: Slot,
        payload: CredentialDeleteRequest,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(bearer_auth),
    ):
        state = get_state()
        ref = reference(slot)
        operation, reused = start_operation(
            "credential_delete",
            ref,
            idempotency_key,
            "DELETE",
            f"/api/v1/credentials/telegram/{slot}",
            await request.body(),
        )
        response.headers["X-Operation-ID"] = operation.operation_id
        if reused:
            return redact_value(state.credentials.get(ref).model_dump(mode="json"))
        try:
            metadata = state.credentials.delete(ref, operation_id=operation.operation_id)
        except CredentialBackendError as exc:
            fail(operation.operation_id, exc)
            raise
        finish(operation.operation_id, metadata)
        return redact_value(metadata.model_dump(mode="json"))

    return router

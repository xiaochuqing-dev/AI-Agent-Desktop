from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CredentialStatus(StrEnum):
    MISSING = "missing"
    AVAILABLE = "available"
    INACCESSIBLE = "inaccessible"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    CORRUPT = "corrupt"
    UNKNOWN = "unknown"


class CredentialPurpose(StrEnum):
    TELEGRAM_BOT_TOKEN = "telegram_bot_token"
    CC_CONNECT_MANAGEMENT_TOKEN = "cc_connect_management_token"
    BINDING_HMAC_KEY = "binding_hmac_key"
    ACCEPTANCE_TEST = "acceptance_test"


class CredentialMetadata(StrictModel):
    reference_id: str = Field(pattern=r"^[a-z][a-z0-9._/-]{2,127}$")
    purpose: CredentialPurpose
    backend: Literal["windows_credential_manager", "memory"]
    revision: int = Field(ge=0)
    status: CredentialStatus
    verified_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CredentialMutationRequest(StrictModel):
    secret: str = Field(
        min_length=1,
        max_length=4096,
        json_schema_extra={"writeOnly": True, "format": "password"},
    )


class CredentialDeleteRequest(StrictModel):
    confirmation: Literal[True]


class CredentialBackendCapability(StrictModel):
    backend_id: Literal["windows_credential_manager", "memory"]
    status: CredentialStatus
    native_windows_backend: bool
    supports_put: bool
    supports_replace: bool
    supports_status: bool
    supports_resolve_for_operation: bool
    supports_delete: bool
    supports_list_metadata: bool
    physical_memory_zeroing_guaranteed: Literal[False] = False
    evidence: dict[str, str | bool] = Field(default_factory=dict)


PUBLIC_CREDENTIAL_REFERENCES: dict[str, tuple[str, CredentialPurpose]] = {
    "hermes": ("telegram/hermes-bot-token", CredentialPurpose.TELEGRAM_BOT_TOKEN),
    "claude": ("telegram/claude-bot-token", CredentialPurpose.TELEGRAM_BOT_TOKEN),
    "codex": ("telegram/codex-bot-token", CredentialPurpose.TELEGRAM_BOT_TOKEN),
}

INTERNAL_CC_CONNECT_MANAGEMENT_REFERENCE = "internal/cc-connect-management-token"
INTERNAL_BINDING_HMAC_REFERENCE = "internal/telegram-binding-hmac-key"


def purpose_for_reference(reference_id: str) -> CredentialPurpose:
    for known_reference, purpose in PUBLIC_CREDENTIAL_REFERENCES.values():
        if reference_id == known_reference:
            return purpose
    if reference_id == INTERNAL_CC_CONNECT_MANAGEMENT_REFERENCE:
        return CredentialPurpose.CC_CONNECT_MANAGEMENT_TOKEN
    if reference_id == INTERNAL_BINDING_HMAC_REFERENCE:
        return CredentialPurpose.BINDING_HMAC_KEY
    if reference_id.startswith("acceptance/"):
        return CredentialPurpose.ACCEPTANCE_TEST
    raise ValueError("unsupported credential reference")

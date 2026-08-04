from __future__ import annotations

import shutil
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import select

from ..configuration.service import canonical_digest
from ..installer.artifacts import InstallerError
from ..persistence.models import HermesConfigurationPlanRecord
from ..persistence.session import Database
from ..telegram.binding_service import TelegramBindingService
from ..telegram.models import BindingState
from .models import (
    HermesConfigurationPlan,
    HermesConfigurationPlanRequest,
    HermesConfigurationState,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class HermesConfigurationPlanner:
    """Render a non-secret plan without taking ownership of an external Hermes install."""

    def __init__(
        self,
        database: Database,
        bindings: TelegramBindingService,
        *,
        path_lookup: Callable[[str], str | None] | None = None,
    ) -> None:
        self.db = database
        self.bindings = bindings
        self.path_lookup = path_lookup or shutil.which

    def create_plan(self, request: HermesConfigurationPlanRequest) -> HermesConfigurationPlan:
        binding = self.bindings.get(request.binding_session_id)
        if (
            binding.state != BindingState.COMPLETED
            or binding.operator_user_id is None
            or binding.group_chat_id is None
        ):
            raise InstallerError(
                "TELEGRAM_BINDING_NOT_COMPLETE",
                "A completed three-bot binding is required for the Hermes Telegram plan.",
                recovery_actions=["complete_three_bot_binding"],
            )
        candidate = self.path_lookup("hermes.exe") or self.path_lookup("hermes")
        installed = bool(candidate)
        status: Literal["plan_ready_external_owner", "pending_component_install"] = (
            "plan_ready_external_owner" if installed else "pending_component_install"
        )
        reason = (
            "Hermes is installed, but its external configuration ownership is preserved; this plan is not applied."
            if installed
            else "Hermes is not installed in the discoverable user environment."
        )
        plan = HermesConfigurationPlan(
            plan_id=f"hermes-plan-{uuid.uuid4().hex[:16]}",
            plan_digest="sha256:" + "0" * 64,
            binding_session_id=binding.session_id,
            status=status,
            installed=installed,
            management_owner="external" if installed else "unknown",
            non_secret_environment={
                "TELEGRAM_ALLOWED_USERS": str(binding.operator_user_id),
                "TELEGRAM_GROUP_ALLOWED_USERS": str(binding.operator_user_id),
                "TELEGRAM_GROUP_ALLOWED_CHATS": str(binding.group_chat_id),
            },
            reason=reason,
            created_at=utcnow(),
        )
        digest = canonical_digest(plan.model_dump(mode="json", exclude={"plan_digest"}))
        plan = plan.model_copy(update={"plan_digest": digest})
        with self.db.session() as session:
            session.add(
                HermesConfigurationPlanRecord(
                    plan_id=plan.plan_id,
                    binding_session_id=plan.binding_session_id,
                    plan_digest=plan.plan_digest,
                    status=plan.status,
                    plan_json=plan.model_dump_json(),
                    created_at=plan.created_at,
                )
            )
        return plan

    def state(self) -> HermesConfigurationState:
        with self.db.session() as session:
            record = session.scalar(
                select(HermesConfigurationPlanRecord).order_by(
                    HermesConfigurationPlanRecord.created_at.desc()
                )
            )
        if record is None:
            return HermesConfigurationState(status="missing_plan")
        plan = HermesConfigurationPlan.model_validate_json(record.plan_json)
        return HermesConfigurationState(status=plan.status, latest_plan=plan)

    @staticmethod
    def discovered_executable_name(candidate: str | None) -> str | None:
        return Path(candidate).name if candidate else None

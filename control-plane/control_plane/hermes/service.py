"""Hermes Telegram native configuration and readiness service."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from ..configuration.service import canonical_digest
from ..installer.artifacts import InstallerError
from ..operations import OperationExecutionError
from ..telegram.api_client import TelegramApiError
from .cli import HermesCliError, HermesCliRunner
from .env_transaction import HermesEnvError, HermesEnvReceipt, HermesEnvTransaction
from .lifecycle import HermesGatewayError, HermesGatewayLifecycle, HermesGatewayStatus
from .models import (
    HermesTelegramApplyRequest,
    HermesTelegramConfigurationPlan,
    HermesTelegramConfigurationPlanRequest,
    HermesTelegramReadinessSnapshot,
)

RollbackCredential = Callable[[], None]


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class _PendingPlan:
    plan: HermesTelegramConfigurationPlan
    binding_session_id: str
    choice: Literal["use_existing", "switch_to_current"]


class HermesTelegramConfigurationAdapter:
    """Coordinates inspection, explicit plan confirmation, env commit and Gateway lifecycle."""

    def __init__(
        self,
        *,
        runner: HermesCliRunner,
        gateway: HermesGatewayLifecycle | None = None,
        token_resolver: Callable[[], str | Iterator[str]] | None = None,
        verify_token: Callable[[str], dict] | None = None,
        binding_resolver: Callable[[str], object] | None = None,
        credential_adopter: Callable[[str, str], RollbackCredential | None] | None = None,
        lease_service=None,
    ) -> None:
        self.runner = runner
        self.gateway = gateway or HermesGatewayLifecycle(runner)
        self.token_resolver = token_resolver
        self.verify_token = verify_token or self._verify_with_telegram
        self.binding_resolver = binding_resolver
        self.credential_adopter = credential_adopter
        self.lease_service = lease_service
        self._plans: dict[str, _PendingPlan] = {}
        self._lock = threading.RLock()
        self._revision = 0

    @staticmethod
    def _lease_owner_value(lease: object) -> str:
        """Normalize real and test lease owners without depending on enum shape."""

        owner = getattr(lease, "owner", "unknown")
        return str(getattr(owner, "value", owner))

    def _env(self) -> HermesEnvTransaction:
        try:
            return HermesEnvTransaction(self.runner.env_path())
        except HermesCliError:
            raise InstallerError(
                "HERMES_ENV_PATH_UNAVAILABLE",
                "无法定位 Hermes 官方 Telegram 配置文件。",
                recovery_actions=["inspect_hermes_installation"],
            ) from None

    def _resolve_token(self) -> str:
        if self.token_resolver is None:
            raise InstallerError(
                "CREDENTIAL_NOT_AVAILABLE", "Hermes Telegram Bot Token 尚未准备好。"
            )
        value = self.token_resolver()
        if hasattr(value, "__enter__"):
            with value as token:  # type: ignore[union-attr]
                return str(token)
        return str(value)

    def _verify_with_telegram(self, token: str) -> dict:
        # The default service is wired with a TelegramBotApiClient in AppState;
        # keeping this fallback deterministic makes direct unit tests possible.
        raise InstallerError(
            "HERMES_TELEGRAM_VERIFY_UNAVAILABLE", "当前环境无法验证 Hermes Telegram Bot 身份。"
        )

    @staticmethod
    def _identity(token: str, verify: Callable[[str], dict]) -> tuple[int, str] | None:
        try:
            payload = verify(token)
            return int(payload["id"]), str(payload.get("username") or "").strip()
        except (InstallerError, TelegramApiError, KeyError, TypeError, ValueError):
            return None

    def inspect(
        self, *, proposed_token: str | None = None, operator_user_id: int | None = None
    ) -> HermesTelegramReadinessSnapshot:
        try:
            env = self._env().inspect()
        except InstallerError as exc:
            return HermesTelegramReadinessSnapshot(
                configuration_status="UNKNOWN",
                bot_identity_status="unknown",
                operator_allowed=False,
                gateway_status="unknown",
                gateway_running=False,
                change_required=False,
                conflict=False,
                diagnostic_code=exc.code,
                user_message="无法安全读取 Hermes Telegram 配置。",
                revision=self._revision,
            )
        if not env.token:
            gateway = self.gateway.status()
            return HermesTelegramReadinessSnapshot(
                configuration_status="UNCONFIGURED",
                bot_identity_status="unknown",
                operator_allowed=False,
                gateway_status=cast(Literal["running", "stopped", "unknown"], gateway.state),
                gateway_running=gateway.running,
                change_required=True,
                conflict=False,
                diagnostic_code="HERMES_TELEGRAM_NOT_CONFIGURED",
                user_message="Hermes 尚未配置 Telegram。",
                revision=self._revision,
            )
        identity = self._identity(env.token, self.verify_token)
        proposed = self._identity(proposed_token, self.verify_token) if proposed_token else None
        operator_allowed = bool(
            operator_user_id is not None and str(operator_user_id) in env.allowed_users
        )
        gateway = self.gateway.status()
        if identity is None:
            status = "INVALID_TOKEN"
            code = "HERMES_TELEGRAM_TOKEN_INVALID"
            message = "Hermes 中已有 Telegram 配置，但 Bot Token 无法验证。"
            conflict = False
        elif proposed and identity[0] != proposed[0]:
            status = "DIFFERENT_BOT"
            code = "HERMES_TELEGRAM_EXISTING_BOT_CONFLICT"
            message = "检测到 Hermes 已连接另一个 Telegram Bot。"
            conflict = True
        elif not operator_allowed:
            status = "PARTIAL"
            code = "HERMES_TELEGRAM_OPERATOR_NOT_ALLOWED"
            message = "Hermes Bot 已配置，但当前操作用户尚未加入允许列表。"
            conflict = False
        else:
            status = "SAME_BOT"
            code = None
            message = "Hermes Telegram 已连接。"
            conflict = False
        return HermesTelegramReadinessSnapshot(
            configuration_status=status,  # type: ignore[arg-type]
            bot_identity_status="verified" if identity else "invalid",
            operator_allowed=operator_allowed,
            gateway_status=cast(Literal["running", "stopped", "unknown"], gateway.state),
            gateway_running=gateway.running,
            change_required=status != "SAME_BOT" or not gateway.running,
            conflict=conflict,
            diagnostic_code=code,
            user_message=message,
            revision=self._revision,
            bot_id=identity[0] if identity else None,
            username=identity[1] if identity else None,
        )

    def _proposed_token(self) -> str | None:
        try:
            return self._resolve_token()
        except (InstallerError, HermesCliError):
            return None

    def create_plan(
        self, request: HermesTelegramConfigurationPlanRequest
    ) -> HermesTelegramConfigurationPlan:
        binding = (
            self.binding_resolver(request.binding_session_id) if self.binding_resolver else None
        )
        operator_user_id = getattr(binding, "operator_user_id", None)
        if not operator_user_id:
            raise InstallerError(
                "TELEGRAM_BINDING_NOT_COMPLETE",
                "完成 Telegram 三 Bot 绑定后才能配置 Hermes。",
                recovery_actions=["complete_three_bot_binding"],
            )
        proposed_token = self._resolve_token()
        readiness = self.inspect(proposed_token=proposed_token, operator_user_id=operator_user_id)
        if (
            readiness.conflict
            and request.choice == "switch_to_current"
            and not request.confirmation
        ):
            raise InstallerError(
                "HERMES_TELEGRAM_CONFLICT_CONFIRMATION_REQUIRED",
                "切换 Hermes 当前 Bot 需要明确确认。",
                recovery_actions=["confirm_hermes_bot_switch"],
            )
        plan = HermesTelegramConfigurationPlan(
            plan_id=f"hermes-telegram-plan-{uuid.uuid4().hex[:16]}",
            plan_digest="sha256:" + "0" * 64,
            binding_session_id=request.binding_session_id,
            status="ready" if readiness.configuration_status != "UNKNOWN" else "needs_action",
            readiness=readiness,
            choice=request.choice,
            expected_changes=[
                "write TELEGRAM_BOT_TOKEN to Hermes official .env",
                "merge the bound operator into TELEGRAM_ALLOWED_USERS",
                "preserve group-wide authorization and TELEGRAM_HOME_CHANNEL",
                "start or restart the official Hermes Gateway without a console window",
            ],
            user_confirmation_required=readiness.conflict,
            created_at=_now(),
        )
        digest = canonical_digest(plan.model_dump(mode="json", exclude={"plan_digest"}))
        plan = plan.model_copy(update={"plan_digest": digest})
        with self._lock:
            self._plans[plan.plan_id] = _PendingPlan(
                plan, request.binding_session_id, request.choice
            )
        return plan

    def confirm_plan(self, request: HermesTelegramApplyRequest) -> tuple[str, bool]:
        with self._lock:
            pending = self._plans.get(request.plan_id)
        if pending is None or pending.plan.plan_digest != request.plan_digest:
            raise InstallerError(
                "HERMES_TELEGRAM_PLAN_NOT_FOUND", "Hermes Telegram 配置计划不存在或已过期。"
            )
        if request.choice != pending.choice or not request.confirmation:
            raise InstallerError(
                "HERMES_TELEGRAM_CONFIRMATION_MISMATCH", "Hermes Telegram 配置确认与计划不匹配。"
            )
        return pending.plan.plan_id, False

    def execute_plan(self, plan_id: str, *, operation_id: str | None = None) -> dict[str, object]:
        with self._lock:
            pending = self._plans.get(plan_id)
        if pending is None:
            raise OperationExecutionError(
                "HERMES_TELEGRAM_PLAN_NOT_FOUND", "Hermes Telegram 配置计划不存在。"
            )
        binding = (
            self.binding_resolver(pending.binding_session_id) if self.binding_resolver else None
        )
        operator_user_id = getattr(binding, "operator_user_id", None)
        if not operator_user_id:
            raise OperationExecutionError(
                "TELEGRAM_BINDING_NOT_COMPLETE", "Telegram 绑定尚未完成。"
            )
        transaction = self._env()
        receipt: HermesEnvReceipt | None = None
        credential_rollback: RollbackCredential | None = None
        prior_gateway: HermesGatewayStatus | None = None
        prior_lease = None
        prior_owner = "none"
        try:
            snapshot = transaction.inspect()
            prior_gateway = self.gateway.status()
            proposed_token = self._resolve_token()
            existing_identity = (
                self._identity(snapshot.token, self.verify_token) if snapshot.token else None
            )
            proposed_identity = self._identity(proposed_token, self.verify_token)
            selected_identity: tuple[int, str] | None
            if pending.choice == "use_existing":
                if not snapshot.token:
                    raise OperationExecutionError(
                        "HERMES_TELEGRAM_EXISTING_BOT_MISSING", "Hermes 没有可复用的既有 Bot。"
                    )
                token = snapshot.token
                selected_identity = existing_identity
            else:
                token = proposed_token
                selected_identity = proposed_identity
                if (
                    existing_identity
                    and proposed_identity
                    and existing_identity[0] != proposed_identity[0]
                ):
                    # The explicit choice is already recorded in the immutable plan.
                    pass
            if pending.choice == "use_existing" and self.credential_adopter is not None:
                # Adoption is explicit and keeps the canonical credential reference
                # aligned with Hermes' already-running Bot. The callback returns an
                # in-memory rollback action; no plaintext backup is persisted.
                try:
                    credential_rollback = self.credential_adopter(
                        token,
                        operation_id or f"hermes-telegram-adopt-{plan_id}",
                    )
                except Exception:
                    # Adapter boundaries must never echo backend details or a
                    # token-shaped exception into the operation result/log.
                    raise OperationExecutionError(
                        "HERMES_CREDENTIAL_ADOPTION_FAILED",
                        "无法安全同步 Hermes Bot 凭据，现有配置未完成切换。",
                        retryable=True,
                        recovery_actions=["inspect_credential_backend", "retry_explicitly"],
                    ) from None
            if not (
                existing_identity
                and proposed_identity
                and existing_identity[0] == proposed_identity[0]
                and str(operator_user_id) in snapshot.allowed_users
            ):
                receipt = transaction.update(token=token, operator_user_id=operator_user_id)

            prior_lease = self.lease_service.get("hermes") if self.lease_service else None
            prior_owner = (
                self._lease_owner_value(prior_lease) if prior_lease is not None else "none"
            )
            if prior_lease is not None and prior_owner not in {"none", "hermes_runtime"}:
                raise OperationExecutionError(
                    "HERMES_GATEWAY_UPDATE_OWNER_CONFLICT",
                    "Hermes 当前由另一个更新消费者占用，未抢占其 Telegram 更新权限。",
                    retryable=True,
                    recovery_actions=["inspect_update_owner", "stop_corresponding_runtime"],
                )
            if prior_lease is not None and prior_owner == "hermes_runtime":
                self.gateway.run_action("stop")
                self.lease_service.release(
                    "hermes",
                    prior_lease.operation_id,
                    "hermes_configuration_handoff",
                )
            gateway = self.gateway.status()
            if not gateway.running:
                gateway = self.gateway.ensure_running(prior=prior_gateway)
            elif receipt is not None:
                gateway = self.gateway.restart()
            if self.lease_service and prior_lease is not None and prior_owner == "hermes_runtime":
                self.lease_service.acquire(
                    "hermes",
                    prior_lease.owner,
                    prior_lease.operation_id or operation_id or plan_id,
                    prior_lease.credential_revision,
                    ttl_seconds=24 * 60 * 60,
                )
            self._revision += 1
            return HermesTelegramReadinessSnapshot(
                configuration_status="SAME_BOT",
                bot_identity_status="verified" if selected_identity else "unknown",
                operator_allowed=True,
                gateway_status=cast(Literal["running", "stopped", "unknown"], gateway.state),
                gateway_running=gateway.running,
                change_required=False,
                conflict=False,
                diagnostic_code=None,
                user_message="Hermes Telegram 已连接。",
                revision=self._revision,
                bot_id=(selected_identity or (None, None))[0],
                username=(selected_identity or (None, None))[1],
            ).model_dump(mode="json")
        except Exception as exc:
            try:
                if receipt is not None:
                    transaction.rollback(receipt)
                if credential_rollback is not None:
                    credential_rollback()
                if prior_gateway is not None:
                    self.gateway.restore(prior_gateway)
                if (
                    self.lease_service
                    and prior_lease is not None
                    and prior_owner == "hermes_runtime"
                    and self._lease_owner_value(self.lease_service.get("hermes"))
                    != "hermes_runtime"
                ):
                    self.lease_service.acquire(
                        "hermes",
                        prior_lease.owner,
                        prior_lease.operation_id or operation_id or plan_id,
                        prior_lease.credential_revision,
                        ttl_seconds=24 * 60 * 60,
                    )
            except Exception:
                pass
            if isinstance(exc, OperationExecutionError):
                code = exc.error.code
                message = exc.error.message
            elif isinstance(exc, (HermesEnvError, HermesGatewayError, InstallerError)):
                code = exc.code
                message = exc.message
            else:
                code = "HERMES_TELEGRAM_APPLY_FAILED"
                message = "Hermes Telegram 配置失败。"
            raise OperationExecutionError(
                code,
                message,
                retryable=True,
                recovery_actions=["inspect_hermes_diagnostics", "retry_hermes_configuration"],
            ) from None

    def readiness(
        self, *, binding_session_id: str | None = None
    ) -> HermesTelegramReadinessSnapshot:
        proposed_token = self._proposed_token()
        operator_user_id: int | None = None
        if binding_session_id and self.binding_resolver is not None:
            binding = self.binding_resolver(binding_session_id)
            raw_operator_user_id = getattr(binding, "operator_user_id", None)
            if raw_operator_user_id is not None:
                operator_user_id = int(raw_operator_user_id)
        return self.inspect(
            proposed_token=proposed_token,
            operator_user_id=operator_user_id,
        )

    @staticmethod
    def gateway_status_model(status: HermesGatewayStatus) -> dict[str, object]:
        return {
            "state": status.state,
            "running": status.running,
            "diagnostic_code": status.diagnostic_code,
            "user_message": status.user_message,
        }

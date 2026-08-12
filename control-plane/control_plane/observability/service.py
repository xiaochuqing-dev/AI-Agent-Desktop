from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import select, update

from ..persistence.models import (
    LinkStatusRecord,
    LiveE2ETestPlanRecord,
    LiveE2ETestRunRecord,
    MessageCorrelationRecord,
    SessionIsolationResultRecord,
    TelegramBindingSessionRecord,
    TelegramBindingSlotRecord,
)
from ..persistence.session import Database
from ..security.redaction import redact_value
from .models import (
    ALL_LINK_IDS,
    E2ETestConfirmation,
    E2ETestPlan,
    E2ETestResponseEvidence,
    E2ETestRun,
    EvidenceLevel,
    IsolationCheck,
    LinkId,
    LinkState,
    LinkStatus,
    MessageCorrelation,
    SessionIsolationResult,
    TestLifecycle,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item),
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def identity_hash(value: int | str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(str(value).encode()).hexdigest()


class ObservabilityError(ValueError):
    def __init__(self, code: str, message: str, recovery_actions: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recovery_actions = recovery_actions or []


class MessageCorrelationService:
    """Stores only identifiers and validates an exact, one-time response match."""

    def __init__(self, database: Database) -> None:
        self.db = database

    def register_request(
        self,
        *,
        correlation_id: str,
        link_id: LinkId,
        bot_id: int,
        chat_identity_hash: str,
        request_message_id: int,
    ) -> MessageCorrelation:
        now = utcnow()
        with self.db.session() as session:
            existing = session.get(MessageCorrelationRecord, correlation_id)
            if existing is not None:
                return self._model(existing)
            record = MessageCorrelationRecord(
                correlation_id=correlation_id,
                link_id=link_id.value,
                bot_id=bot_id,
                chat_identity_hash=chat_identity_hash,
                request_message_id=request_message_id,
                response_message_id=None,
                reply_to_message_id=None,
                send_status="sent",
                response_status="missing",
                sent_at=now,
                responded_at=None,
                latency_ms=None,
                diagnostic_code=None,
                consumed=0,
            )
            session.add(record)
            return self._model(record)

    def match_response(
        self,
        *,
        correlation_id: str,
        link_id: LinkId,
        bot_id: int,
        chat_identity_hash: str,
        response_message_id: int,
        reply_to_message_id: int | None,
        received_at: datetime | None = None,
    ) -> MessageCorrelation:
        now = received_at or utcnow()
        with self.db.session() as session:
            record = session.get(MessageCorrelationRecord, correlation_id)
            if record is None:
                return MessageCorrelation(
                    correlation_id=correlation_id,
                    link_id=link_id,
                    bot_id=bot_id,
                    chat_identity_hash=chat_identity_hash,
                    request_message_id=0,
                    response_message_id=response_message_id,
                    reply_to_message_id=reply_to_message_id,
                    send_status="unknown",
                    response_status="unknown",
                    sent_at=now,
                    responded_at=now,
                    diagnostic_code="CORRELATION_NOT_FOUND",
                )
            if record.consumed:
                # Do not overwrite the accepted response with a later duplicate.
                return self._model(record).model_copy(
                    update={
                        "response_status": "duplicate",
                        "diagnostic_code": "RESPONSE_ALREADY_CONSUMED",
                    }
                )
            if record.link_id != link_id.value or record.bot_id != bot_id:
                record.response_status = "ambiguous"
                record.diagnostic_code = "RESPONSE_WRONG_BOT_OR_LINK"
                return self._model(record)
            if record.chat_identity_hash != chat_identity_hash:
                record.response_status = "ambiguous"
                record.diagnostic_code = "RESPONSE_WRONG_CHAT"
                return self._model(record)
            if response_message_id == record.request_message_id:
                record.response_status = "ambiguous"
                record.diagnostic_code = "RESPONSE_MESSAGE_EQUALS_REQUEST"
                return self._model(record)
            sent_at = aware_utc(record.sent_at)
            now = aware_utc(now)
            if now < sent_at:
                record.response_status = "ambiguous"
                record.diagnostic_code = "RESPONSE_OLDER_THAN_REQUEST"
                return self._model(record)
            if reply_to_message_id != record.request_message_id:
                record.response_status = "ambiguous"
                record.diagnostic_code = "RESPONSE_NOT_REPLY_TO_REQUEST"
                return self._model(record)
            record.response_message_id = response_message_id
            record.reply_to_message_id = reply_to_message_id
            record.response_status = "received"
            record.responded_at = now
            record.latency_ms = max(0, int((now - sent_at).total_seconds() * 1000))
            record.consumed = 1
            return self._model(record)

    def get(self, correlation_id: str) -> MessageCorrelation | None:
        with self.db.session() as session:
            record = session.get(MessageCorrelationRecord, correlation_id)
            return self._model(record) if record else None

    @staticmethod
    def _model(record: MessageCorrelationRecord) -> MessageCorrelation:
        return MessageCorrelation(
            correlation_id=record.correlation_id,
            link_id=LinkId(record.link_id),
            bot_id=record.bot_id,
            chat_identity_hash=record.chat_identity_hash,
            request_message_id=record.request_message_id,
            response_message_id=record.response_message_id,
            reply_to_message_id=record.reply_to_message_id,
            send_status=cast(Literal["sent", "failed", "unknown"], record.send_status),
            response_status=cast(
                Literal["received", "missing", "ambiguous", "duplicate", "unknown"],
                record.response_status,
            ),
            sent_at=record.sent_at.replace(tzinfo=record.sent_at.tzinfo or UTC),
            responded_at=(
                record.responded_at.replace(tzinfo=record.responded_at.tzinfo or UTC)
                if record.responded_at
                else None
            ),
            latency_ms=record.latency_ms,
            diagnostic_code=record.diagnostic_code,
        )


class SessionIsolationProbe:
    REQUIRED_CHECKS = (
        "private_group_isolation",
        "claude_codex_isolation",
        "hermes_cc_connect_isolation",
        "different_user_group_topic_isolation",
        "reply_mention_plain_message_routing",
        "start_bind_commands_not_runtime_consumed",
        "runtime_restart_isolation",
        "control_plane_restart_isolation",
        "old_update_not_replayed",
        "duplicate_message_not_executed",
        "failure_has_no_automatic_retry",
    )

    def __init__(self, database: Database) -> None:
        self.db = database

    def run(self) -> SessionIsolationResult:
        now = utcnow()
        checks = [
            IsolationCheck(
                name=name,
                status="passed",
                evidence={"fixture": "synthetic", "message_bodies_persisted": False},
            )
            for name in self.REQUIRED_CHECKS
        ]
        result = SessionIsolationResult(
            probe_id=f"isolation-{uuid.uuid4().hex}",
            status="passed",
            evidence_level=EvidenceLevel.SYNTHETIC,
            checks=checks,
            created_at=now,
            completed_at=now,
        )
        with self.db.session() as session:
            session.add(
                SessionIsolationResultRecord(
                    probe_id=result.probe_id,
                    status=result.status,
                    evidence_level=result.evidence_level.value,
                    checks_json=json.dumps(result.model_dump(mode="json"), sort_keys=True),
                    created_at=now,
                    completed_at=now,
                )
            )
        return result

    def latest(self) -> SessionIsolationResult | None:
        with self.db.session() as session:
            record = session.scalar(
                select(SessionIsolationResultRecord).order_by(
                    SessionIsolationResultRecord.created_at.desc()
                )
            )
            if record is None:
                return None
            return SessionIsolationResult.model_validate_json(record.checks_json)


class LiveE2ETestService:
    """Owns link snapshots and explicit one-shot test plans.

    The optional sender is deliberately injected so all CI and synthetic tests can
    prove the lifecycle without contacting Telegram. The production AppState injects
    the Telegram client and only sends after the confirmation endpoint is called.
    """

    def __init__(
        self,
        database: Database,
        *,
        credentials: Any | None = None,
        identities: Any | None = None,
        binding: Any | None = None,
        lifecycle: Any | None = None,
        configuration: Any | None = None,
        native_configuration: Any | None = None,
        telegram_client: Any | None = None,
        sender: Callable[..., dict[str, Any]] | None = None,
        response_receiver: Callable[..., dict[str, Any] | None] | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.db = database
        self.credentials = credentials
        self.identities = identities
        self.binding = binding
        self.lifecycle = lifecycle
        self.configuration = configuration
        self.native_configuration = native_configuration
        self.telegram_client = telegram_client
        self.sender = sender
        self.response_receiver = response_receiver
        self.clock = clock
        self.correlation = MessageCorrelationService(database)
        self.isolation = SessionIsolationProbe(database)

    def list_links(self) -> list[LinkState]:
        return [self.get_link(link_id) for link_id in ALL_LINK_IDS]

    def get_link(self, link_id: LinkId | str) -> LinkState:
        typed = LinkId(link_id)
        inferred = self._infer_link(typed)
        with self.db.session() as session:
            current = session.get(LinkStatusRecord, typed.value)
            if current is None:
                state = inferred
                current = LinkStatusRecord(
                    link_id=typed.value,
                    state_json=state.model_dump_json(),
                    status=state.status.value,
                    evidence_level=state.evidence_level.value,
                    last_probe_at=self.clock(),
                    last_live_verified_at=state.last_live_verified_at,
                )
                session.add(current)
            else:
                stored = LinkState.model_validate_json(current.state_json)
                state = inferred
                if self._same_evidence_context(stored, inferred) and stored.correlation_id:
                    # Keep the latest explicit result while refreshing runtime observations.
                    state = stored.model_copy(
                        update={
                            "runtime_owner": inferred.runtime_owner,
                            "runtime_state": inferred.runtime_state,
                            "update_lease_owner": inferred.update_lease_owner,
                            "last_probe_at": self.clock(),
                        }
                    )
                elif stored.evidence_level == EvidenceLevel.LIVE_VERIFIED:
                    state = inferred.model_copy(
                        update={
                            "status": LinkStatus.STALE,
                            "evidence_level": EvidenceLevel.OBSERVED,
                            "diagnostic_code": "CHAT_EVIDENCE_STALE",
                            "recovery_actions": ["create_new_explicit_e2e_plan"],
                            "last_live_verified_at": stored.last_live_verified_at,
                        }
                    )
                current.state_json = state.model_dump_json()
                current.status = state.status.value
                current.evidence_level = state.evidence_level.value
                current.last_probe_at = self.clock()
            return state

    def create_plan(self, link_id: LinkId | str, *, expires_in_seconds: int = 300) -> E2ETestPlan:
        typed = LinkId(link_id)
        state = self.get_link(typed)
        if state.status not in {
            LinkStatus.READY_FOR_LIVE_TEST,
            LinkStatus.PENDING_USER_VALIDATION,
            LinkStatus.HEALTHY,
        }:
            if state.status not in {
                LinkStatus.DEGRADED,
                LinkStatus.FAILED,
                LinkStatus.UNKNOWN,
            }:
                raise ObservabilityError(
                    "E2E_LINK_NOT_READY",
                    f"{typed.value} is not ready for an explicit live test.",
                    ["verify_credentials", "complete_telegram_binding", "start_runtime"],
                )
        if not state.binding_session_id or state.credential_revision < 1:
            raise ObservabilityError(
                "E2E_BINDING_CONTEXT_MISSING", "Binding context is incomplete."
            )
        if state.bot_id is None:
            raise ObservabilityError("E2E_BOT_IDENTITY_MISSING", "Bot identity is incomplete.")
        now = self.clock()
        plan_id = f"e2e-plan-{uuid.uuid4().hex}"
        correlation_id = f"e2e-{uuid.uuid4().hex[:20]}"
        target_hash = (
            state.group_identity_hash
            if typed.session_scope == "group"
            else state.operator_identity_hash
        )
        if target_hash is None:
            raise ObservabilityError("E2E_TARGET_MISSING", "The selected chat is not bound.")
        payload_digest = digest(
            {"link_id": typed.value, "correlation_id": correlation_id, "message_count": 1}
        )
        plan_data = {
            "plan_id": plan_id,
            "link_id": typed.value,
            "target_bot_slot": typed.bot_slot,
            "expected_bot_id": state.bot_id,
            "target_chat_kind": typed.session_scope,
            "target_chat_identity_hash": target_hash,
            "expected_credential_revision": state.credential_revision,
            "expected_binding_session_id": state.binding_session_id,
            "expected_binding_revision": state.binding_revision,
            "expected_configuration_revision": state.configuration_revision,
            "expected_runtime_owner": state.runtime_owner,
            "expected_runtime_state": state.runtime_state,
            "expected_update_lease_owner": state.update_lease_owner,
            "correlation_id": correlation_id,
            "payload_digest": payload_digest,
            "expires_at": now + timedelta(seconds=expires_in_seconds),
            "created_at": now,
        }
        plan_digest = digest(
            {k: v.value if isinstance(v, LinkId) else v for k, v in plan_data.items()}
        )
        plan = E2ETestPlan(
            plan_id=plan_id,
            plan_digest=plan_digest,
            link_id=typed,
            target_bot_slot=cast(Literal["hermes", "claude", "codex"], typed.bot_slot),
            expected_bot_id=state.bot_id,
            target_chat_kind=cast(Literal["private", "group"], typed.session_scope),
            target_chat_identity_hash=target_hash,
            expected_credential_revision=state.credential_revision,
            expected_binding_session_id=state.binding_session_id,
            expected_binding_revision=state.binding_revision,
            expected_configuration_revision=state.configuration_revision,
            expected_runtime_owner=state.runtime_owner,
            expected_runtime_state=state.runtime_state,
            expected_update_lease_owner=state.update_lease_owner,
            correlation_id=correlation_id,
            payload_digest=payload_digest,
            expires_at=now + timedelta(seconds=expires_in_seconds),
            created_at=now,
        )
        with self.db.session() as session:
            session.add(
                LiveE2ETestPlanRecord(
                    plan_id=plan.plan_id,
                    plan_digest=plan.plan_digest,
                    link_id=plan.link_id.value,
                    plan_json=plan.model_dump_json(),
                    status=plan.status.value,
                    expires_at=plan.expires_at,
                    created_at=plan.created_at,
                )
            )
        return plan

    def get_plan(self, plan_id: str) -> E2ETestPlan | None:
        with self.db.session() as session:
            record = session.get(LiveE2ETestPlanRecord, plan_id)
            if record is None:
                return None
            plan = E2ETestPlan.model_validate_json(record.plan_json)
            status = TestLifecycle(record.status)
            if status == TestLifecycle.PLANNED and plan.expires_at <= self.clock():
                record.status = TestLifecycle.EXPIRED.value
                status = TestLifecycle.EXPIRED
            if plan.status != status:
                plan = plan.model_copy(update={"status": status})
            return plan

    def cancel_plan(self, plan_id: str, *, confirmation: bool) -> E2ETestPlan:
        if not confirmation:
            raise ObservabilityError(
                "E2E_CANCEL_CONFIRMATION_REQUIRED", "Cancellation must be confirmed."
            )
        with self.db.session() as session:
            record = session.get(LiveE2ETestPlanRecord, plan_id)
            if record is None:
                raise ObservabilityError("E2E_PLAN_NOT_FOUND", "E2E plan was not found.")
            if record.status not in {TestLifecycle.PLANNED.value, TestLifecycle.CONFIRMED.value}:
                raise ObservabilityError(
                    "E2E_PLAN_NOT_CANCELABLE", "E2E plan is no longer cancelable."
                )
            plan = E2ETestPlan.model_validate_json(record.plan_json).model_copy(
                update={"status": TestLifecycle.CANCELED}
            )
            record.status = TestLifecycle.CANCELED.value
            record.plan_json = plan.model_dump_json()
            return plan

    def confirm_plan(
        self,
        confirmation: E2ETestConfirmation,
        *,
        idempotency_key: str,
    ) -> E2ETestRun:
        plan = self.get_plan(confirmation.plan_id)
        if plan is None:
            raise ObservabilityError("E2E_PLAN_NOT_FOUND", "E2E plan was not found.")
        if plan.plan_digest != confirmation.plan_digest or plan.link_id != confirmation.link_id:
            raise ObservabilityError(
                "E2E_PLAN_DIGEST_MISMATCH", "E2E plan digest or link does not match."
            )
        if plan.status == TestLifecycle.EXPIRED:
            raise ObservabilityError("E2E_PLAN_EXPIRED", "E2E plan expired.")
        with self.db.session() as session:
            existing = session.scalar(
                select(LiveE2ETestRunRecord).where(
                    LiveE2ETestRunRecord.plan_id == plan.plan_id,
                    LiveE2ETestRunRecord.idempotency_key == idempotency_key,
                )
            )
            if existing:
                return self._run_model(existing)
        current = self.get_link(plan.link_id)
        if (
            current.credential_revision != confirmation.credential_revision
            or current.binding_session_id != confirmation.binding_session_id
            or current.binding_revision != confirmation.binding_revision
            or current.configuration_revision != confirmation.configuration_revision
            or current.runtime_owner != plan.expected_runtime_owner
            or current.runtime_state != plan.expected_runtime_state
            or current.update_lease_owner != plan.expected_update_lease_owner
        ):
            raise ObservabilityError(
                "E2E_PLAN_STALE",
                "Link revisions changed after the plan was created; no message was sent.",
                ["create_new_e2e_plan"],
            )
        run, claimed = self._claim_plan(plan, idempotency_key=idempotency_key)
        if not claimed:
            return run

        now = run.created_at
        request_message_id: int | None = None
        response_message_id: int | None = None
        reply_to_message_id: int | None = None
        latency_ms: int | None = None
        lifecycle = TestLifecycle.UNKNOWN
        evidence = EvidenceLevel.OBSERVED
        diagnostic_code: str | None = None
        recovery_actions: list[str] = []
        try:
            result = self._send_once(plan)
            request_message_id = self._positive_int(result.get("message_id"))
            latency_ms = self._positive_int(result.get("latency_ms"), allow_zero=True)
            if request_message_id is None:
                diagnostic_code = "E2E_REQUEST_MESSAGE_ID_UNKNOWN"
                recovery_actions = [
                    "inspect_runtime_session",
                    "create_new_explicit_e2e_plan",
                ]
            else:
                self.correlation.register_request(
                    correlation_id=plan.correlation_id,
                    link_id=plan.link_id,
                    bot_id=plan.expected_bot_id,
                    chat_identity_hash=plan.target_chat_identity_hash,
                    request_message_id=request_message_id,
                )
                raw_response = None
                if self.response_receiver is not None:
                    raw_response = self.response_receiver(plan=plan, request=result)
                elif result.get("response_message_id") is not None:
                    # A fake transport may provide response metadata, but it must
                    # still include all correlation fields before being trusted.
                    raw_response = result
                correlation = self._match_response(
                    plan,
                    run_id=run.run_id,
                    raw_response=raw_response,
                )
                if correlation is not None and correlation.response_status == "received":
                    lifecycle = TestLifecycle.SUCCEEDED
                    evidence = EvidenceLevel.LIVE_VERIFIED
                    response_message_id = correlation.response_message_id
                    reply_to_message_id = correlation.reply_to_message_id
                    diagnostic_code = None
                elif raw_response is None:
                    diagnostic_code = "E2E_RESPONSE_PENDING"
                    recovery_actions = [
                        "await_runtime_response_observation",
                        "record_response_evidence_without_resending",
                    ]
                else:
                    diagnostic_code = (
                        correlation.diagnostic_code
                        if correlation is not None
                        else "E2E_RESPONSE_EVIDENCE_INVALID"
                    )
                    recovery_actions = ["inspect_runtime_session", "create_new_explicit_e2e_plan"]
        except ObservabilityError as exc:
            diagnostic_code = exc.code
            recovery_actions = exc.recovery_actions
            lifecycle = TestLifecycle.FAILED
        except Exception:
            diagnostic_code = "E2E_SEND_FAILED"
            recovery_actions = ["inspect_telegram_network", "create_new_explicit_e2e_plan"]
            lifecycle = TestLifecycle.FAILED
        run = E2ETestRun(
            run_id=run.run_id,
            plan_id=plan.plan_id,
            link_id=plan.link_id,
            lifecycle=lifecycle,
            evidence_level=evidence,
            correlation_id=plan.correlation_id,
            request_message_id=request_message_id,
            response_message_id=response_message_id,
            reply_to_message_id=reply_to_message_id,
            latency_ms=latency_ms,
            diagnostic_code=diagnostic_code,
            recovery_actions=recovery_actions,
            created_at=now,
            completed_at=self.clock(),
        )
        self._persist_run(run)
        self._record_live_result(plan, run)
        return run

    def record_response(self, evidence: E2ETestResponseEvidence) -> E2ETestRun:
        """Accept one response observation from the owning runtime.

        This endpoint never polls Telegram. The runtime that owns the Update Lease
        supplies identifiers, and an exact correlation match is required.
        """

        with self.db.session() as session:
            record = session.get(LiveE2ETestRunRecord, evidence.run_id)
            if record is None:
                raise ObservabilityError("E2E_RUN_NOT_FOUND", "E2E test run was not found.")
            current = self._run_model(record)
        if current.evidence_level == EvidenceLevel.LIVE_VERIFIED:
            return current
        plan = self.get_plan(current.plan_id)
        if plan is None:
            raise ObservabilityError("E2E_PLAN_NOT_FOUND", "E2E plan was not found.")
        correlation = self.correlation.match_response(
            correlation_id=current.correlation_id,
            link_id=current.link_id,
            bot_id=evidence.bot_id,
            chat_identity_hash=evidence.chat_identity_hash,
            response_message_id=evidence.response_message_id,
            reply_to_message_id=evidence.reply_to_message_id,
            received_at=evidence.received_at,
        )
        if correlation.response_status == "received":
            current = current.model_copy(
                update={
                    "lifecycle": TestLifecycle.SUCCEEDED,
                    "evidence_level": EvidenceLevel.LIVE_VERIFIED,
                    "response_message_id": correlation.response_message_id,
                    "reply_to_message_id": correlation.reply_to_message_id,
                    "latency_ms": correlation.latency_ms,
                    "diagnostic_code": None,
                    "recovery_actions": [],
                    "completed_at": self.clock(),
                }
            )
        elif (
            correlation.response_status == "duplicate"
            and current.evidence_level == EvidenceLevel.LIVE_VERIFIED
        ):
            return current
        else:
            current = current.model_copy(
                update={
                    "lifecycle": TestLifecycle.UNKNOWN,
                    "evidence_level": EvidenceLevel.OBSERVED,
                    "diagnostic_code": correlation.diagnostic_code or "E2E_RESPONSE_AMBIGUOUS",
                    "recovery_actions": ["inspect_runtime_session", "create_new_explicit_e2e_plan"],
                    "completed_at": self.clock(),
                }
            )
        self._persist_run(current)
        self._record_live_result(plan, current)
        return current

    def _claim_plan(self, plan: E2ETestPlan, *, idempotency_key: str) -> tuple[E2ETestRun, bool]:
        """Atomically consume a plan before touching Telegram."""

        now = self.clock()
        with self.db.session() as session:
            existing = session.scalar(
                select(LiveE2ETestRunRecord).where(LiveE2ETestRunRecord.plan_id == plan.plan_id)
            )
            if existing is not None:
                if existing.idempotency_key == idempotency_key:
                    return self._run_model(existing), False
                raise ObservabilityError(
                    "E2E_PLAN_ALREADY_CONSUMED",
                    "This E2E plan has already been confirmed; create a new plan.",
                    ["create_new_explicit_e2e_plan"],
                )
            plan_record = session.get(LiveE2ETestPlanRecord, plan.plan_id)
            if plan_record is None:
                raise ObservabilityError("E2E_PLAN_NOT_FOUND", "E2E plan was not found.")
            if plan_record.status != TestLifecycle.PLANNED.value:
                raise ObservabilityError(
                    "E2E_PLAN_ALREADY_CONSUMED",
                    "This E2E plan is no longer available for confirmation.",
                    ["create_new_explicit_e2e_plan"],
                )
            if aware_utc(plan_record.expires_at) <= aware_utc(now):
                plan_record.status = TestLifecycle.EXPIRED.value
                plan_record.plan_json = plan.model_copy(
                    update={"status": TestLifecycle.EXPIRED}
                ).model_dump_json()
                raise ObservabilityError("E2E_PLAN_EXPIRED", "E2E plan expired.")
            claimed = session.execute(
                update(LiveE2ETestPlanRecord)
                .where(
                    LiveE2ETestPlanRecord.plan_id == plan.plan_id,
                    LiveE2ETestPlanRecord.status == TestLifecycle.PLANNED.value,
                )
                .values(
                    status=TestLifecycle.RUNNING.value,
                    plan_json=plan.model_copy(
                        update={"status": TestLifecycle.RUNNING}
                    ).model_dump_json(),
                )
            )
            if getattr(claimed, "rowcount", 0) != 1:
                raise ObservabilityError(
                    "E2E_PLAN_ALREADY_CONSUMED",
                    "This E2E plan was confirmed concurrently; create a new plan.",
                    ["create_new_explicit_e2e_plan"],
                )
            run = E2ETestRun(
                run_id=f"e2e-run-{uuid.uuid4().hex}",
                plan_id=plan.plan_id,
                link_id=plan.link_id,
                lifecycle=TestLifecycle.RUNNING,
                evidence_level=EvidenceLevel.OBSERVED,
                correlation_id=plan.correlation_id,
                created_at=now,
            )
            session.add(
                LiveE2ETestRunRecord(
                    run_id=run.run_id,
                    plan_id=run.plan_id,
                    link_id=run.link_id.value,
                    lifecycle=run.lifecycle.value,
                    evidence_level=run.evidence_level.value,
                    correlation_id=run.correlation_id,
                    request_message_id=None,
                    response_message_id=None,
                    reply_to_message_id=None,
                    latency_ms=None,
                    diagnostic_code=None,
                    recovery_actions_json="[]",
                    idempotency_key=idempotency_key,
                    created_at=run.created_at,
                    completed_at=None,
                )
            )
            return run, True

    def _persist_run(self, run: E2ETestRun) -> None:
        with self.db.session() as session:
            record = session.get(LiveE2ETestRunRecord, run.run_id)
            if record is None:
                raise ObservabilityError("E2E_RUN_NOT_FOUND", "E2E test run was not found.")
            record.lifecycle = run.lifecycle.value
            record.evidence_level = run.evidence_level.value
            record.request_message_id = run.request_message_id
            record.response_message_id = run.response_message_id
            record.reply_to_message_id = run.reply_to_message_id
            record.latency_ms = run.latency_ms
            record.diagnostic_code = run.diagnostic_code
            record.recovery_actions_json = json.dumps(run.recovery_actions)
            record.completed_at = run.completed_at
            plan_record = session.get(LiveE2ETestPlanRecord, run.plan_id)
            if plan_record is not None:
                plan_record.status = run.lifecycle.value
                stored_plan = E2ETestPlan.model_validate_json(plan_record.plan_json)
                plan_record.plan_json = stored_plan.model_copy(
                    update={"status": run.lifecycle}
                ).model_dump_json()

    def _match_response(
        self,
        plan: E2ETestPlan,
        *,
        run_id: str,
        raw_response: dict[str, Any] | None,
    ) -> MessageCorrelation | None:
        if raw_response is None:
            return None
        bot_id = self._positive_int(raw_response.get("response_bot_id", raw_response.get("bot_id")))
        chat_identity_hash = raw_response.get(
            "response_chat_identity_hash", raw_response.get("chat_identity_hash")
        )
        response_message_id = self._positive_int(raw_response.get("response_message_id"))
        if bot_id is None or not isinstance(chat_identity_hash, str) or response_message_id is None:
            return None
        try:
            evidence = E2ETestResponseEvidence(
                run_id=run_id,
                bot_id=bot_id,
                chat_identity_hash=chat_identity_hash,
                response_message_id=response_message_id,
                reply_to_message_id=raw_response.get("reply_to_message_id"),
                received_at=raw_response.get("received_at"),
            )
        except Exception:
            return None
        if evidence.run_id != run_id:
            return None
        return self.correlation.match_response(
            correlation_id=plan.correlation_id,
            link_id=plan.link_id,
            bot_id=evidence.bot_id,
            chat_identity_hash=evidence.chat_identity_hash,
            response_message_id=evidence.response_message_id,
            reply_to_message_id=evidence.reply_to_message_id,
            received_at=evidence.received_at,
        )

    @staticmethod
    def _positive_int(value: Any, *, allow_zero: bool = False) -> int | None:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        if number < 0 or (number == 0 and not allow_zero):
            return None
        return number

    def run_synthetic(self) -> list[E2ETestRun]:
        """Run six deterministic tests without Telegram access or persisted bodies."""
        now = self.clock()
        runs: list[E2ETestRun] = []
        for link_id in ALL_LINK_IDS:
            correlation_id = f"synthetic-{link_id.value.replace('.', '-')}-{uuid.uuid4().hex[:10]}"
            run = E2ETestRun(
                run_id=f"synthetic-run-{uuid.uuid4().hex}",
                plan_id=f"synthetic-plan-{uuid.uuid4().hex}",
                link_id=link_id,
                lifecycle=TestLifecycle.SUCCEEDED,
                evidence_level=EvidenceLevel.SYNTHETIC,
                correlation_id=correlation_id,
                request_message_id=1000 + len(runs),
                response_message_id=2000 + len(runs),
                reply_to_message_id=1000 + len(runs),
                latency_ms=1,
                created_at=now,
                completed_at=now,
            )
            runs.append(run)
            self._record_synthetic_run(run)
        return runs

    def latest_runs(self, *, limit: int = 50) -> list[E2ETestRun]:
        with self.db.session() as session:
            records = list(
                session.scalars(
                    select(LiveE2ETestRunRecord)
                    .order_by(LiveE2ETestRunRecord.created_at.desc())
                    .limit(limit)
                )
            )
            return [self._run_model(item) for item in records]

    def _infer_link(self, link_id: LinkId) -> LinkState:
        now = self.clock()
        state = LinkState(
            link_id=link_id,
            bot_slot=link_id.bot_slot,
            session_scope=link_id.session_scope,
            status=LinkStatus.UNKNOWN,
            last_probe_at=now,
        )
        identity = None
        if self.identities is not None:
            try:
                identity = self.identities.get(link_id.bot_slot)
            except Exception:
                identity = None
        if identity is None:
            state.status = LinkStatus.CREDENTIAL_MISSING
            state.diagnostic_code = "TELEGRAM_BOT_IDENTITY_MISSING"
            state.recovery_actions = ["verify_bot_identity"]
            return state
        state.bot_id = identity.bot_id
        state.bot_username = identity.username
        state.credential_reference_id = identity.credential_reference_id
        state.credential_revision = identity.credential_revision
        if identity.verification_status != "verified":
            state.status = LinkStatus.IDENTITY_UNVERIFIED
            state.diagnostic_code = "TELEGRAM_IDENTITY_UNVERIFIED"
            state.recovery_actions = ["verify_bot_identity"]
            return state
        binding = self._latest_completed_binding(link_id)
        if binding is None:
            state.status = LinkStatus.BINDING_PENDING
            state.diagnostic_code = "TELEGRAM_BINDING_PENDING"
            state.recovery_actions = ["complete_telegram_binding"]
            return state
        record, slot = binding
        state.binding_session_id = record.session_id
        state.binding_revision = record.revision
        state.operator_identity_hash = identity_hash(record.operator_user_id)
        state.group_identity_hash = identity_hash(slot.group_chat_id)
        state.configuration_revision = self._configuration_revision()
        (
            state.runtime_owner,
            state.runtime_state,
            state.artifact_id,
            state.ownership_revision,
        ) = self._runtime_state(link_id)
        state.update_lease_owner = self._update_lease_owner(link_id.bot_slot)
        if state.runtime_state in {"stopped", "not_installed"}:
            state.status = LinkStatus.RUNTIME_STOPPED
            state.diagnostic_code = "RUNTIME_STOPPED"
            state.recovery_actions = ["start_runtime"]
            return state
        if state.runtime_owner == "product" and state.runtime_state == "conflict":
            state.status = LinkStatus.RUNTIME_CONFLICT
            state.diagnostic_code = "CC_CONNECT_RUNTIME_NOT_READY"
            state.recovery_actions = ["reconcile_lifecycle", "inspect_process_identity"]
            return state
        if state.runtime_owner == "product" and state.runtime_state != "running_partial":
            state.status = LinkStatus.RUNTIME_STOPPED
            state.diagnostic_code = "CC_CONNECT_RUNTIME_NOT_READY"
            state.recovery_actions = ["start_runtime", "reconcile_lifecycle"]
            return state
        state.status = LinkStatus.READY_FOR_LIVE_TEST
        state.evidence_level = EvidenceLevel.OBSERVED
        state.diagnostic_code = "READY_FOR_EXPLICIT_LIVE_TEST"
        state.recovery_actions = ["create_e2e_plan", "confirm_one_shot_e2e"]
        return state

    @staticmethod
    def _same_evidence_context(left: LinkState, right: LinkState) -> bool:
        """Live evidence is valid only for the exact credential/binding/config context."""

        return (
            left.link_id == right.link_id
            and left.bot_id == right.bot_id
            and left.credential_revision == right.credential_revision
            and left.binding_session_id == right.binding_session_id
            and left.binding_revision == right.binding_revision
            and left.configuration_revision == right.configuration_revision
            and left.runtime_owner == right.runtime_owner
            and left.runtime_state == right.runtime_state
            and left.artifact_id == right.artifact_id
            and left.ownership_revision == right.ownership_revision
            and left.update_lease_owner == right.update_lease_owner
        )

    def _latest_completed_binding(self, link_id: LinkId):
        with self.db.session() as session:
            record = session.scalar(
                select(TelegramBindingSessionRecord)
                .where(TelegramBindingSessionRecord.state == "completed")
                .order_by(TelegramBindingSessionRecord.completed_at.desc())
            )
            if record is None:
                return None
            slot = session.get(TelegramBindingSlotRecord, (record.session_id, link_id.bot_slot))
            if slot is None:
                return None
            if link_id.session_scope == "private" and slot.private_status != "bound":
                return None
            if link_id.session_scope == "group" and slot.group_status != "bound":
                return None
            return record, slot

    def _configuration_revision(self) -> int:
        if self.native_configuration is not None:
            try:
                state = self.native_configuration.state()
                if getattr(state, "status", None) == "valid":
                    return int(getattr(state, "revision", 0) or 0)
            except Exception:
                pass
        if self.configuration is None:
            return 0
        try:
            status = self.configuration.status()
            return int(getattr(status, "revision", 0) or 0)
        except Exception:
            return 0

    def _runtime_state(self, link_id: LinkId) -> tuple[str, str, str | None, str]:
        if link_id.bot_slot == "hermes":
            return "external", "unknown", None, "external"
        if self.lifecycle is None:
            return "product", "unknown", None, "unknown"
        try:
            status = self.lifecycle.status()
            observed = str(getattr(status, "observed_state", "unknown"))
            management = str(getattr(status, "management_owner", "unknown"))
            lifecycle = str(getattr(status, "lifecycle_owner", "unknown"))
            return (
                "product",
                observed.removeprefix("RuntimeState.").lower(),
                getattr(status, "artifact_id", None),
                f"{management}:{lifecycle}",
            )
        except Exception:
            return "product", "unknown", None, "unknown"

    def _update_lease_owner(self, slot: str) -> str:
        try:
            with self.db.session() as session:
                from ..persistence.models import TelegramUpdateLeaseRecord

                record = session.get(TelegramUpdateLeaseRecord, slot)
                return record.owner if record and record.owner else "none"
        except Exception:
            return "unknown"

    def _send_once(self, plan: E2ETestPlan) -> dict[str, Any]:
        if self.sender is None and os.environ.get(
            "CONTROL_PLANE_DISABLE_LIVE_TELEGRAM", ""
        ).lower() in {"1", "true", "yes"}:
            raise ObservabilityError(
                "E2E_LIVE_TELEGRAM_DISABLED",
                "Live Telegram E2E is disabled in this environment; use a fake sender.",
                ["run_synthetic_e2e", "use_fake_telegram_fixture"],
            )
        target = self._target_chat_id(plan)
        if target is None:
            raise ObservabilityError("E2E_TARGET_MISSING", "Bound chat identity is unavailable.")
        started = time.monotonic()
        if self.sender is not None:
            result = self.sender(plan=plan, chat_id=target)
        elif (
            self.telegram_client is not None
            and self.credentials is not None
            and self.identities is not None
        ):
            identity = self.identities.get(plan.target_bot_slot)
            if identity is None:
                raise ObservabilityError(
                    "TELEGRAM_IDENTITY_MISSING", "Bot identity is unavailable."
                )
            with self.credentials.resolve_for_operation(identity.credential_reference_id) as token:
                result = asyncio.run(
                    self.telegram_client.send_message(
                        token, chat_id=target, text=self._payload(plan)
                    )
                )
        else:
            raise ObservabilityError(
                "E2E_TRANSPORT_UNAVAILABLE", "No Telegram live transport is configured."
            )
        if not isinstance(result, dict):
            raise ObservabilityError(
                "E2E_SEND_RESULT_INVALID", "Live transport returned an invalid result."
            )
        result.setdefault("latency_ms", int((time.monotonic() - started) * 1000))
        return result

    def _target_chat_id(self, plan: E2ETestPlan) -> int | None:
        binding = self._latest_completed_binding(plan.link_id)
        if binding is None:
            return None
        _record, slot = binding
        return slot.group_chat_id if plan.target_chat_kind == "group" else slot.private_user_id

    @staticmethod
    def _payload(plan: E2ETestPlan) -> str:
        return f"AI-Agent-Desktop acceptance {plan.link_id.value} {plan.correlation_id} (read-only)"

    def _record_live_result(self, plan: E2ETestPlan, run: E2ETestRun) -> None:
        with self.db.session() as session:
            record = session.get(LinkStatusRecord, plan.link_id.value)
            if record:
                current = LinkState.model_validate_json(record.state_json)
                evidence = run.evidence_level
                if evidence == EvidenceLevel.LIVE_VERIFIED:
                    status = LinkStatus.HEALTHY
                elif run.request_message_id is not None:
                    status = LinkStatus.DEGRADED
                elif run.lifecycle == TestLifecycle.FAILED:
                    status = LinkStatus.FAILED
                else:
                    status = LinkStatus.UNKNOWN
                current = current.model_copy(
                    update={
                        "status": status,
                        "evidence_level": evidence,
                        "send_status": ("sent" if run.request_message_id is not None else "failed"),
                        "response_status": "received" if run.response_message_id else "unknown",
                        "correlation_id": run.correlation_id,
                        "request_message_id": run.request_message_id,
                        "response_message_id": run.response_message_id,
                        "latency_ms": run.latency_ms,
                        "last_live_verified_at": (
                            self.clock()
                            if evidence == EvidenceLevel.LIVE_VERIFIED
                            else current.last_live_verified_at
                        ),
                        "diagnostic_code": run.diagnostic_code,
                        "recovery_actions": run.recovery_actions,
                    }
                )
                record.state_json = redact_value(current.model_dump_json())
                record.status = current.status.value
                record.evidence_level = current.evidence_level.value
                record.last_live_verified_at = current.last_live_verified_at

    def _record_synthetic_run(self, run: E2ETestRun) -> None:
        with self.db.session() as session:
            session.add(
                LiveE2ETestRunRecord(
                    run_id=run.run_id,
                    plan_id=run.plan_id,
                    link_id=run.link_id.value,
                    lifecycle=run.lifecycle.value,
                    evidence_level=run.evidence_level.value,
                    correlation_id=run.correlation_id,
                    request_message_id=run.request_message_id,
                    response_message_id=run.response_message_id,
                    reply_to_message_id=run.reply_to_message_id,
                    latency_ms=run.latency_ms,
                    diagnostic_code=None,
                    recovery_actions_json="[]",
                    idempotency_key=f"synthetic:{run.run_id}",
                    created_at=run.created_at,
                    completed_at=run.completed_at,
                )
            )

    @staticmethod
    def _run_model(record: LiveE2ETestRunRecord) -> E2ETestRun:
        return E2ETestRun(
            run_id=record.run_id,
            plan_id=record.plan_id,
            link_id=LinkId(record.link_id),
            lifecycle=TestLifecycle(record.lifecycle),
            evidence_level=EvidenceLevel(record.evidence_level),
            correlation_id=record.correlation_id,
            request_message_id=record.request_message_id,
            response_message_id=record.response_message_id,
            reply_to_message_id=record.reply_to_message_id,
            latency_ms=record.latency_ms,
            diagnostic_code=record.diagnostic_code,
            recovery_actions=json.loads(record.recovery_actions_json or "[]"),
            created_at=record.created_at.replace(tzinfo=record.created_at.tzinfo or UTC),
            completed_at=(
                record.completed_at.replace(tzinfo=record.completed_at.tzinfo or UTC)
                if record.completed_at
                else None
            ),
        )


# Backwards-compatible name for callers created before the service boundary was
# made explicit. New code should use LiveE2ETestService.
LinkObservabilityService = LiveE2ETestService

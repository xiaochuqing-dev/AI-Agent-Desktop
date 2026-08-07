from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from control_plane.infrastructure.config import Settings
from control_plane.observability.models import (
    E2ETestConfirmation,
    E2ETestResponseEvidence,
    EvidenceLevel,
    LinkId,
    LinkStatus,
)
from control_plane.observability.models import TestLifecycle as Lifecycle
from control_plane.observability.service import (
    LinkObservabilityService,
    MessageCorrelationService,
    ObservabilityError,
    identity_hash,
)
from control_plane.persistence.models import (
    TelegramBindingSessionRecord,
    TelegramBindingSlotRecord,
)
from control_plane.persistence.session import Database
from control_plane.telegram.models import TelegramBotIdentity


class FakeIdentities:
    def __init__(self):
        self.items = {
            slot: TelegramBotIdentity(
                slot=slot,
                bot_id=1000 + index,
                username=f"{slot}_bot",
                first_name=slot.title(),
                can_join_groups=True,
                can_read_all_group_messages=True,
                credential_reference_id=f"telegram/{slot}-bot-token",
                credential_revision=1,
                verified_at=datetime.now(UTC),
                verification_status="verified",
            )
            for index, slot in enumerate(("hermes", "claude", "codex"), start=1)
        }

    def get(self, slot):
        return self.items.get(slot)


class FakeLifecycle:
    def status(self):
        return SimpleNamespace(observed_state="running")


class FakeConfiguration:
    def status(self):
        return SimpleNamespace(revision=3)


def seed_binding(database: Database) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    with database.session() as session:
        session.add(
            TelegramBindingSessionRecord(
                session_id="binding-test",
                code_digest="hmac-sha256:test",
                state="completed",
                expires_at=now + timedelta(hours=1),
                operator_user_id=42,
                group_chat_id=-10042,
                group_title="Test",
                group_type="supergroup",
                revision=7,
                created_at=now,
                updated_at=now,
                completed_at=now,
                canceled_at=None,
                failure_code=None,
            )
        )
        for slot, bot_id in zip(("hermes", "claude", "codex"), (1001, 1002, 1003), strict=True):
            session.add(
                TelegramBindingSlotRecord(
                    session_id="binding-test",
                    slot=slot,
                    bot_id=bot_id,
                    username=f"{slot}_bot",
                    credential_revision=1,
                    private_status="bound",
                    group_status="bound",
                    private_user_id=42,
                    group_chat_id=-10042,
                    group_title="Test",
                    group_type="supergroup",
                    private_update_id=10,
                    group_update_id=20,
                    last_update_id=20,
                    updated_at=now,
                )
            )


def test_six_links_have_independent_states_and_synthetic_runs(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    seed_binding(database)
    calls = []

    def sender(**kwargs):
        calls.append(kwargs)
        return {
            "message_id": 901,
            "response_message_id": 902,
            "reply_to_message_id": 901,
            "response_bot_id": 1002,
            "response_chat_identity_hash": identity_hash(42),
        }

    service = LinkObservabilityService(
        database,
        identities=FakeIdentities(),
        lifecycle=FakeLifecycle(),
        configuration=FakeConfiguration(),
        sender=sender,
    )
    links = service.list_links()
    assert [item.link_id for item in links] == list(LinkId)
    assert all(item.status == LinkStatus.READY_FOR_LIVE_TEST for item in links)

    plan = service.create_plan(LinkId.CLAUDE_PRIVATE)
    confirmation = {
        "plan_id": plan.plan_id,
        "plan_digest": plan.plan_digest,
        "link_id": plan.link_id,
        "credential_revision": plan.expected_credential_revision,
        "binding_session_id": plan.expected_binding_session_id,
        "binding_revision": plan.expected_binding_revision,
        "configuration_revision": plan.expected_configuration_revision,
        "confirmation": True,
    }
    payload = E2ETestConfirmation(**confirmation)
    run = service.confirm_plan(payload, idempotency_key="one-shot-key-123456")
    assert run.lifecycle.value == "succeeded"
    assert run.evidence_level == EvidenceLevel.LIVE_VERIFIED
    assert run.automatic_retry is False
    assert len(calls) == 1
    same = service.confirm_plan(payload, idempotency_key="one-shot-key-123456")
    assert same.run_id == run.run_id
    assert len(calls) == 1
    with pytest.raises(ObservabilityError) as caught:
        service.confirm_plan(payload, idempotency_key="different-key-123456")
    assert caught.value.code == "E2E_PLAN_ALREADY_CONSUMED"
    assert len(calls) == 1

    synthetic = service.run_synthetic()
    assert len(synthetic) == 6
    assert all(item.evidence_level == EvidenceLevel.SYNTHETIC for item in synthetic)
    assert all(item.evidence_level != EvidenceLevel.LIVE_VERIFIED for item in synthetic)


def test_send_without_response_stays_observed_until_exact_runtime_evidence(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    seed_binding(database)
    calls = []

    def sender(**kwargs):
        calls.append(kwargs)
        return {"message_id": 901}

    service = LinkObservabilityService(
        database,
        identities=FakeIdentities(),
        lifecycle=FakeLifecycle(),
        configuration=FakeConfiguration(),
        sender=sender,
    )
    plan = service.create_plan(LinkId.CLAUDE_PRIVATE)
    confirmation = E2ETestConfirmation(
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        link_id=plan.link_id,
        credential_revision=plan.expected_credential_revision,
        binding_session_id=plan.expected_binding_session_id,
        binding_revision=plan.expected_binding_revision,
        configuration_revision=plan.expected_configuration_revision,
        confirmation=True,
    )
    run = service.confirm_plan(confirmation, idempotency_key="pending-response-123456")
    assert run.lifecycle == Lifecycle.UNKNOWN
    assert run.evidence_level == EvidenceLevel.OBSERVED
    assert run.diagnostic_code == "E2E_RESPONSE_PENDING"
    assert len(calls) == 1
    link = service.get_link(LinkId.CLAUDE_PRIVATE)
    assert link.status == LinkStatus.DEGRADED
    assert link.last_live_verified_at is None

    verified = service.record_response(
        E2ETestResponseEvidence(
            run_id=run.run_id,
            bot_id=plan.expected_bot_id,
            chat_identity_hash=plan.target_chat_identity_hash,
            response_message_id=902,
            reply_to_message_id=901,
        )
    )
    assert verified.lifecycle == Lifecycle.SUCCEEDED
    assert verified.evidence_level == EvidenceLevel.LIVE_VERIFIED
    assert service.get_link(LinkId.CLAUDE_PRIVATE).status == LinkStatus.HEALTHY

    identities = service.identities
    identities.items["claude"] = identities.items["claude"].model_copy(
        update={"credential_revision": 2}
    )
    stale = service.get_link(LinkId.CLAUDE_PRIVATE)
    assert stale.status == LinkStatus.READY_FOR_LIVE_TEST
    assert stale.evidence_level != EvidenceLevel.LIVE_VERIFIED
    assert stale.last_live_verified_at is None


def test_failed_send_is_never_retried_for_the_same_plan(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    seed_binding(database)
    calls = 0

    def sender(**_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError("synthetic timeout")

    service = LinkObservabilityService(
        database,
        identities=FakeIdentities(),
        lifecycle=FakeLifecycle(),
        configuration=FakeConfiguration(),
        sender=sender,
    )
    plan = service.create_plan(LinkId.CODEX_GROUP)
    confirmation = E2ETestConfirmation(
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        link_id=plan.link_id,
        credential_revision=plan.expected_credential_revision,
        binding_session_id=plan.expected_binding_session_id,
        binding_revision=plan.expected_binding_revision,
        configuration_revision=plan.expected_configuration_revision,
        confirmation=True,
    )
    first = service.confirm_plan(confirmation, idempotency_key="failed-send-key-123456")
    second = service.confirm_plan(confirmation, idempotency_key="failed-send-key-123456")
    assert first.lifecycle == Lifecycle.FAILED
    assert second.run_id == first.run_id
    assert calls == 1
    with pytest.raises(ObservabilityError):
        service.confirm_plan(confirmation, idempotency_key="failed-new-key-123456")
    assert calls == 1


def test_message_correlation_rejects_wrong_chat_old_and_duplicate(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    correlation = MessageCorrelationService(database)
    sent = datetime.now(UTC)
    record = correlation.register_request(
        correlation_id="corr-test",
        link_id=LinkId.HERMES_GROUP,
        bot_id=1,
        chat_identity_hash="chat-a",
        request_message_id=10,
    )
    wrong = correlation.match_response(
        correlation_id=record.correlation_id,
        link_id=LinkId.HERMES_GROUP,
        bot_id=1,
        chat_identity_hash="chat-b",
        response_message_id=11,
        reply_to_message_id=10,
    )
    assert wrong.response_status == "ambiguous"
    old = correlation.match_response(
        correlation_id=record.correlation_id,
        link_id=LinkId.HERMES_GROUP,
        bot_id=1,
        chat_identity_hash="chat-a",
        response_message_id=12,
        reply_to_message_id=10,
        received_at=sent - timedelta(seconds=1),
    )
    assert old.response_status == "ambiguous"
    accepted = correlation.match_response(
        correlation_id=record.correlation_id,
        link_id=LinkId.HERMES_GROUP,
        bot_id=1,
        chat_identity_hash="chat-a",
        response_message_id=13,
        reply_to_message_id=10,
    )
    assert accepted.response_status == "received"
    duplicate = correlation.match_response(
        correlation_id=record.correlation_id,
        link_id=LinkId.HERMES_GROUP,
        bot_id=1,
        chat_identity_hash="chat-a",
        response_message_id=13,
        reply_to_message_id=10,
    )
    assert duplicate.response_status == "duplicate"
    assert correlation.get(record.correlation_id).response_status == "received"


def test_message_id_cannot_be_reused_as_its_own_response(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    correlation = MessageCorrelationService(database)
    record = correlation.register_request(
        correlation_id="same-message",
        link_id=LinkId.HERMES_PRIVATE,
        bot_id=1,
        chat_identity_hash="chat-a",
        request_message_id=10,
    )
    result = correlation.match_response(
        correlation_id=record.correlation_id,
        link_id=LinkId.HERMES_PRIVATE,
        bot_id=1,
        chat_identity_hash="chat-a",
        response_message_id=10,
        reply_to_message_id=10,
    )
    assert result.response_status == "ambiguous"
    assert result.diagnostic_code == "RESPONSE_MESSAGE_EQUALS_REQUEST"


def test_isolation_probe_covers_required_synthetic_matrix(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    service = LinkObservabilityService(database)
    result = service.isolation.run()
    assert result.status == "passed"
    assert result.evidence_level == EvidenceLevel.SYNTHETIC
    assert len(result.checks) >= 11


def test_ci_guard_never_uses_real_telegram_transport(tmp_path, monkeypatch):
    database = Database(Settings(data_dir=str(tmp_path)))
    seed_binding(database)
    service = LinkObservabilityService(
        database,
        identities=FakeIdentities(),
        lifecycle=FakeLifecycle(),
        configuration=FakeConfiguration(),
    )
    monkeypatch.setenv("CONTROL_PLANE_DISABLE_LIVE_TELEGRAM", "1")
    plan = service.create_plan(LinkId.CLAUDE_PRIVATE)
    confirmation = E2ETestConfirmation(
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        link_id=plan.link_id,
        credential_revision=plan.expected_credential_revision,
        binding_session_id=plan.expected_binding_session_id,
        binding_revision=plan.expected_binding_revision,
        configuration_revision=plan.expected_configuration_revision,
        confirmation=True,
    )
    run = service.confirm_plan(confirmation, idempotency_key="ci-guard-key-123456")
    assert run.lifecycle == Lifecycle.FAILED
    assert run.diagnostic_code == "E2E_LIVE_TELEGRAM_DISABLED"
    assert run.request_message_id is None


def test_runtime_owner_change_invalidates_plan_before_send(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    seed_binding(database)
    calls = []

    def sender(**kwargs):
        calls.append(kwargs)
        return {"message_id": 11}

    service = LinkObservabilityService(
        database,
        identities=FakeIdentities(),
        lifecycle=FakeLifecycle(),
        configuration=FakeConfiguration(),
        sender=sender,
    )
    plan = service.create_plan(LinkId.CODEX_PRIVATE)
    service.lifecycle.status = lambda: SimpleNamespace(observed_state="stopped")
    confirmation = E2ETestConfirmation(
        plan_id=plan.plan_id,
        plan_digest=plan.plan_digest,
        link_id=plan.link_id,
        credential_revision=plan.expected_credential_revision,
        binding_session_id=plan.expected_binding_session_id,
        binding_revision=plan.expected_binding_revision,
        configuration_revision=plan.expected_configuration_revision,
        confirmation=True,
    )
    with pytest.raises(ObservabilityError) as caught:
        service.confirm_plan(confirmation, idempotency_key="owner-change-key-123456")
    assert caught.value.code == "E2E_PLAN_STALE"
    assert calls == []

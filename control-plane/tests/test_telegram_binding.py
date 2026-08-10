from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest

from control_plane.credentials.models import PUBLIC_CREDENTIAL_REFERENCES
from control_plane.credentials.service import CredentialService
from control_plane.credentials.windows_backend import InMemorySecretBackend
from control_plane.infrastructure.config import Settings
from control_plane.operations import ExecutionContext, OperationExecutionError
from control_plane.persistence.models import (
    TelegramBindingSessionRecord,
    TelegramGroupBindingRecord,
)
from control_plane.persistence.session import Database
from control_plane.telegram.binding_service import SLOTS
from control_plane.telegram.bot_identity import TelegramBotIdentityService
from control_plane.telegram.models import BindingState, UpdateOwner

from .telegram_helpers import (
    TOKENS,
    FakeTelegramClient,
    build_telegram_services,
    complete_binding,
    membership_update,
    message_update,
)


def poll(database, bindings, session_id: str, slot: str, operation_id: str):
    return bindings.poll(
        ExecutionContext(
            operation_id=operation_id,
            component_id=f"telegram:{slot}",
            kind="telegram_binding_poll",
            payload={"session_id": session_id, "slot": slot, "timeout_seconds": 0},
            database=database,
            shutdown_event=threading.Event(),
        )
    )


def test_three_bot_binding_discovers_same_user_group_and_releases_owner(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    _backend, _credentials, client, _identities, leases, bindings = build_telegram_services(
        database
    )
    created, completed = complete_binding(database, client, bindings)

    assert completed.state == BindingState.COMPLETED
    assert completed.operator_user_id == 777001
    assert completed.group_chat_id == -100777001
    assert completed.bound_private_count == 3
    assert completed.bound_group_count == 3
    assert all(leases.get(slot).owner == UpdateOwner.NONE for slot in SLOTS)
    with database.session() as session:
        record = session.get(TelegramBindingSessionRecord, created.session_id)
        assert record is not None
        assert record.code_digest.startswith("hmac-sha256:")
        assert created.bind_code not in record.code_digest
        groups = list(
            session.query(TelegramGroupBindingRecord).filter_by(session_id=created.session_id)
        )
        assert len(groups) == 3
    assert created.bind_code.encode() not in (tmp_path / "control_plane.db").read_bytes()


def test_binding_rejects_other_user_old_update_channel_and_replay(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    _backend, _credentials, client, _identities, _leases, bindings = build_telegram_services(
        database
    )
    created = bindings.create(expires_in_seconds=900)
    client.add_update(
        "hermes",
        1,
        message_update(
            update_id=1,
            text=created.private_commands["hermes"],
            sender_id=100,
            chat_id=100,
            chat_type="private",
        ),
    )
    poll(database, bindings, created.session_id, "hermes", "poll-hermes-private")

    client.add_update(
        "claude",
        2,
        message_update(
            update_id=2,
            text=created.private_commands["claude"],
            sender_id=200,
            chat_id=200,
            chat_type="private",
        ),
    )
    poll(database, bindings, created.session_id, "claude", "poll-claude-hijack")
    state = bindings.get(created.session_id)
    claude = next(item for item in state.slots if item.slot == "claude")
    assert claude.private_status == "rejected"

    client.add_update(
        "codex",
        3,
        message_update(
            update_id=3,
            text=created.private_commands["codex"],
            sender_id=100,
            chat_id=-1001,
            chat_type="channel",
        ),
    )
    poll(database, bindings, created.session_id, "codex", "poll-codex-channel")
    codex = next(item for item in bindings.get(created.session_id).slots if item.slot == "codex")
    assert codex.private_status == "pending"

    client.add_update(
        "hermes",
        4,
        message_update(
            update_id=4,
            text=created.private_commands["hermes"],
            sender_id=100,
            chat_id=100,
            chat_type="private",
        ),
    )
    poll(database, bindings, created.session_id, "hermes", "poll-hermes-replay")
    hermes = next(item for item in bindings.get(created.session_id).slots if item.slot == "hermes")
    assert hermes.private_status == "bound"


def test_group_consistency_conflict_is_detected(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    _backend, _credentials, client, _identities, _leases, bindings = build_telegram_services(
        database
    )
    created = bindings.create(expires_in_seconds=900)
    for index, slot in enumerate(SLOTS, start=1):
        client.add_update(
            slot,
            index,
            message_update(
                update_id=index,
                text=created.private_commands[slot],
                sender_id=555,
                chat_id=555,
                chat_type="private",
            ),
        )
        poll(database, bindings, created.session_id, slot, f"private-{slot}")
    group_ids = {"hermes": -1001, "claude": -1001, "codex": -1002}
    for index, slot in enumerate(SLOTS, start=11):
        client.add_update(
            slot,
            index,
            message_update(
                update_id=index,
                text=created.group_commands[slot],
                sender_id=555,
                chat_id=group_ids[slot],
                chat_type="supergroup",
            ),
        )
        poll(database, bindings, created.session_id, slot, f"group-{slot}")
    assert bindings.get(created.session_id).state == BindingState.CONFLICT


def test_my_chat_member_auto_binds_three_bots_and_rejects_wrong_slot(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    _backend, _credentials, client, _identities, _leases, bindings = build_telegram_services(
        database
    )
    created = bindings.create(expires_in_seconds=900)
    assert all(f"?start=bind_{slot}_" in created.private_deep_links[slot] for slot in SLOTS)

    # A deep link claim is tied to the slot that received the update.
    client.add_update(
        "hermes",
        1,
        message_update(
            update_id=1,
            text="/start bind_claude_" + created.bind_code,
            sender_id=777,
            chat_id=777,
            chat_type="private",
        ),
    )
    poll(database, bindings, created.session_id, "hermes", "wrong-slot")
    assert (
        next(
            item for item in bindings.get(created.session_id).slots if item.slot == "hermes"
        ).private_status
        == "pending"
    )

    for index, slot in enumerate(SLOTS, start=10):
        client.add_update(
            slot,
            index,
            message_update(
                update_id=index,
                text=created.private_commands[slot],
                sender_id=777,
                chat_id=777,
                chat_type="private",
            ),
        )
        poll(database, bindings, created.session_id, slot, f"private-{slot}")

    for index, slot in enumerate(SLOTS, start=20):
        client.add_update(
            slot, index, membership_update(update_id=index, sender_id=777, chat_id=-100777)
        )
        poll(database, bindings, created.session_id, slot, f"membership-{slot}")

    state = bindings.get(created.session_id)
    assert state.state == BindingState.COMPLETED
    assert state.bound_group_count == 3
    assert state.group_chat_id == -100777


def test_my_chat_member_wrong_operator_and_leave_are_not_success(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    _backend, _credentials, client, _identities, _leases, bindings = build_telegram_services(
        database
    )
    created = bindings.create(expires_in_seconds=900)
    for index, slot in enumerate(SLOTS, start=1):
        client.add_update(
            slot,
            index,
            message_update(
                update_id=index,
                text=created.private_commands[slot],
                sender_id=888,
                chat_id=888,
                chat_type="private",
            ),
        )
        poll(database, bindings, created.session_id, slot, f"private-{slot}")
    client.add_update(
        "hermes",
        30,
        membership_update(update_id=30, sender_id=999, chat_id=-1009),
    )
    poll(database, bindings, created.session_id, "hermes", "wrong-operator")
    assert (
        next(
            item for item in bindings.get(created.session_id).slots if item.slot == "hermes"
        ).group_status
        == "pending"
    )

    client.add_update(
        "hermes",
        31,
        membership_update(update_id=31, sender_id=888, chat_id=-1009, status="left"),
    )
    poll(database, bindings, created.session_id, "hermes", "left")
    assert (
        next(
            item for item in bindings.get(created.session_id).slots if item.slot == "hermes"
        ).group_status
        == "rejected"
    )


def test_membership_before_private_waits_for_fresh_membership_evidence(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    _backend, _credentials, client, _identities, _leases, bindings = build_telegram_services(
        database
    )
    created = bindings.create(expires_in_seconds=900)

    client.add_update(
        "hermes",
        1,
        membership_update(update_id=1, sender_id=700, chat_id=-100700),
    )
    poll(database, bindings, created.session_id, "hermes", "membership-before-private")
    hermes = next(item for item in bindings.get(created.session_id).slots if item.slot == "hermes")
    assert hermes.private_status == "pending"
    assert hermes.group_status == "pending"

    client.add_update(
        "hermes",
        2,
        message_update(
            update_id=2,
            text=created.private_commands["hermes"],
            sender_id=700,
            chat_id=700,
            chat_type="private",
        ),
    )
    poll(database, bindings, created.session_id, "hermes", "private-after-membership")
    hermes = next(item for item in bindings.get(created.session_id).slots if item.slot == "hermes")
    assert hermes.private_status == "bound"
    assert hermes.group_status == "pending"

    client.add_update(
        "hermes",
        3,
        membership_update(update_id=3, sender_id=700, chat_id=-100700),
    )
    poll(database, bindings, created.session_id, "hermes", "fresh-membership")
    hermes = next(item for item in bindings.get(created.session_id).slots if item.slot == "hermes")
    assert hermes.group_status == "bound"
    assert hermes.group_chat_id == -100700


def test_old_membership_update_does_not_bind_current_session(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    _backend, _credentials, client, _identities, _leases, bindings = build_telegram_services(
        database
    )
    created = bindings.create(expires_in_seconds=900)
    client.add_update(
        "hermes",
        10,
        message_update(
            update_id=10,
            text=created.private_commands["hermes"],
            sender_id=701,
            chat_id=701,
            chat_type="private",
        ),
    )
    poll(database, bindings, created.session_id, "hermes", "private-before-old-membership")

    client.add_update(
        "hermes",
        11,
        membership_update(
            update_id=11,
            sender_id=701,
            chat_id=-100701,
            membership_date=int(created.created_at.timestamp()) - 60,
        ),
    )
    poll(database, bindings, created.session_id, "hermes", "old-membership")
    hermes = next(item for item in bindings.get(created.session_id).slots if item.slot == "hermes")
    assert hermes.group_status == "pending"
    assert hermes.group_chat_id is None

    client.add_update(
        "hermes",
        12,
        membership_update(update_id=12, sender_id=701, chat_id=-100701),
    )
    poll(database, bindings, created.session_id, "hermes", "current-membership")
    hermes = next(item for item in bindings.get(created.session_id).slots if item.slot == "hermes")
    assert hermes.group_status == "bound"


def test_bot_can_recover_after_leaving_and_rejoining_group(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    _backend, _credentials, client, _identities, _leases, bindings = build_telegram_services(
        database
    )
    created = bindings.create(expires_in_seconds=900)
    client.add_update(
        "hermes",
        20,
        message_update(
            update_id=20,
            text=created.private_commands["hermes"],
            sender_id=702,
            chat_id=702,
            chat_type="private",
        ),
    )
    poll(database, bindings, created.session_id, "hermes", "private-before-rejoin")

    for update_id, status in ((21, "member"), (22, "left"), (23, "member")):
        client.add_update(
            "hermes",
            update_id,
            membership_update(
                update_id=update_id,
                sender_id=702,
                chat_id=-100702,
                status=status,
            ),
        )
        poll(database, bindings, created.session_id, "hermes", f"membership-{status}-{update_id}")
        hermes = next(
            item for item in bindings.get(created.session_id).slots if item.slot == "hermes"
        )
        assert hermes.group_status == ("rejected" if status == "left" else "bound")

    assert hermes.group_chat_id == -100702


def test_plain_group_start_is_safe_startgroup_fallback_after_private_binding(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    _backend, _credentials, client, _identities, _leases, bindings = build_telegram_services(
        database
    )
    created = bindings.create(expires_in_seconds=900)
    assert "?startgroup=bind_hermes_" in created.group_deep_links["hermes"]
    client.add_update(
        "hermes",
        29,
        message_update(
            update_id=29,
            text="/start",
            sender_id=703,
            chat_id=-100703,
            chat_type="supergroup",
        ),
    )
    poll(database, bindings, created.session_id, "hermes", "plain-group-start-before-private")
    hermes = next(item for item in bindings.get(created.session_id).slots if item.slot == "hermes")
    assert hermes.group_status == "pending"

    client.add_update(
        "hermes",
        30,
        message_update(
            update_id=30,
            text=created.private_commands["hermes"],
            sender_id=703,
            chat_id=703,
            chat_type="private",
        ),
    )
    poll(database, bindings, created.session_id, "hermes", "private-before-plain-start")

    client.add_update(
        "hermes",
        31,
        message_update(
            update_id=31,
            text="/start",
            sender_id=703,
            chat_id=-100703,
            chat_type="supergroup",
            title="Startgroup fallback",
        ),
    )
    poll(database, bindings, created.session_id, "hermes", "plain-group-start")
    hermes = next(item for item in bindings.get(created.session_id).slots if item.slot == "hermes")
    assert hermes.group_status == "bound"
    assert hermes.group_chat_id == -100703


def test_same_bot_identity_and_webhook_or_lease_conflicts_are_blocked(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    backend = InMemorySecretBackend()
    credentials = CredentialService(database, backend)
    client = FakeTelegramClient()
    identities = TelegramBotIdentityService(database, credentials, client)  # type: ignore[arg-type]
    credentials.put(
        PUBLIC_CREDENTIAL_REFERENCES["hermes"][0],
        TOKENS["hermes"],
        operation_id="hermes-put",
    )
    credentials.put(
        PUBLIC_CREDENTIAL_REFERENCES["claude"][0],
        TOKENS["hermes"],
        operation_id="claude-put",
    )
    identities.verify("hermes")
    with pytest.raises(OperationExecutionError) as duplicate:
        identities.verify("claude")
    assert duplicate.value.error.code == "TELEGRAM_BOT_IDENTITY_CONFLICT"

    guarded_database = Database(Settings(data_dir=str(tmp_path / "guards")))
    _backend, _credentials, client, _identities, leases, bindings = build_telegram_services(
        guarded_database
    )
    leases.acquire("hermes", UpdateOwner.EXTERNAL, "external-owner", 1)
    with pytest.raises(OperationExecutionError) as lease_conflict:
        bindings.create(expires_in_seconds=900)
    assert lease_conflict.value.error.code == "TELEGRAM_UPDATE_OWNER_NOT_RELEASED"
    leases.release("hermes", "external-owner", "test")

    created = bindings.create(expires_in_seconds=900)
    client.webhooks[TOKENS["hermes"]] = True
    with pytest.raises(OperationExecutionError) as webhook_conflict:
        poll(
            guarded_database,
            bindings,
            created.session_id,
            "hermes",
            "webhook-conflict",
        )
    assert webhook_conflict.value.error.code == "TELEGRAM_WEBHOOK_CONFLICT"
    assert bindings.get(created.session_id).state == BindingState.CONFLICT
    assert leases.get("hermes").owner == UpdateOwner.NONE


def test_resume_reissues_one_time_code_without_losing_slot_progress(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    _backend, _credentials, client, _identities, _leases, bindings = build_telegram_services(
        database
    )
    created = bindings.create(expires_in_seconds=900)
    client.add_update(
        "hermes",
        1,
        message_update(
            update_id=1,
            text=created.private_commands["hermes"],
            sender_id=777,
            chat_id=777,
            chat_type="private",
        ),
    )
    poll(database, bindings, created.session_id, "hermes", "resume-private")
    before = bindings.get(created.session_id)
    assert before.bound_private_count == 1

    resumed = bindings.resume(created.session_id, expires_in_seconds=900)
    assert resumed.session_id == created.session_id
    assert resumed.bind_code != created.bind_code
    assert resumed.bound_private_count == 1
    assert resumed.bound_group_count == 0
    assert resumed.revision == created.revision + 2
    assert resumed.private_deep_links["hermes"] != created.private_deep_links["hermes"]

    client.add_update(
        "claude",
        2,
        message_update(
            update_id=2,
            text=created.private_commands["claude"],
            sender_id=777,
            chat_id=777,
            chat_type="private",
        ),
    )
    poll(database, bindings, created.session_id, "claude", "resume-old-code")
    assert (
        next(
            item for item in bindings.get(created.session_id).slots if item.slot == "claude"
        ).private_status
        == "pending"
    )

    client.add_update(
        "claude",
        3,
        message_update(
            update_id=3,
            text=resumed.private_commands["claude"],
            sender_id=777,
            chat_id=777,
            chat_type="private",
        ),
    )
    poll(database, bindings, created.session_id, "claude", "resume-new-code")
    assert (
        next(
            item for item in bindings.get(created.session_id).slots if item.slot == "claude"
        ).private_status
        == "bound"
    )

    with database.session() as session:
        record = session.get(TelegramBindingSessionRecord, created.session_id)
        assert record is not None
        assert created.bind_code.encode() not in (tmp_path / "control_plane.db").read_bytes()
        assert resumed.bind_code.encode() not in (tmp_path / "control_plane.db").read_bytes()
        assert record.code_digest != ""


def test_resume_does_not_revive_expired_session(tmp_path):
    database = Database(Settings(data_dir=str(tmp_path)))
    _backend, _credentials, _client, _identities, _leases, bindings = build_telegram_services(
        database
    )
    created = bindings.create(expires_in_seconds=900)
    with database.session() as session:
        record = session.get(TelegramBindingSessionRecord, created.session_id)
        assert record is not None
        record.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(OperationExecutionError) as expired:
        bindings.resume(created.session_id, expires_in_seconds=900)
    assert expired.value.error.code == "TELEGRAM_BINDING_EXPIRED"
    assert bindings.get(created.session_id).state == BindingState.EXPIRED

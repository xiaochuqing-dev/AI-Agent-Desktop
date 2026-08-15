from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from control_plane.hermes.cli import HermesCliError, HermesCliRunner, HermesCommandResult
from control_plane.hermes.env_transaction import (
    HermesEnvError,
    HermesEnvTransaction,
    merge_allowed_users,
)
from control_plane.hermes.lifecycle import (
    HermesGatewayLifecycle,
    HermesGatewayStatus,
)
from control_plane.hermes.models import (
    HermesTelegramConfigurationPlanRequest,
)
from control_plane.hermes.service import HermesTelegramConfigurationAdapter
from control_plane.installer.artifacts import InstallerError
from control_plane.operations import OperationExecutionError
from control_plane.telegram.models import UpdateOwner

EXISTING_SECRET = "existing-secret-value"
CURRENT_SECRET = "current-secret-value"


class FakeRunner:
    def __init__(self, env_path: Path) -> None:
        self._env_path = env_path

    def env_path(self) -> Path:
        return self._env_path


class FakeGateway:
    def __init__(self, *, running: bool = False, fail_action: str | None = None) -> None:
        self.running = running
        self.fail_action = fail_action
        self.actions: list[str] = []

    def status(self) -> HermesGatewayStatus:
        return HermesGatewayStatus(
            "running" if self.running else "stopped",
            self.running,
            user_message="synthetic gateway state",
        )

    def ensure_running(self, *, prior=None) -> HermesGatewayStatus:
        del prior
        self.actions.append("start")
        if self.fail_action == "start":
            from control_plane.hermes.lifecycle import HermesGatewayError

            raise HermesGatewayError("HERMES_GATEWAY_START_FAILED", "Gateway start failed.")
        self.running = True
        return self.status()

    def run_action(self, action: str) -> HermesGatewayStatus:
        self.actions.append(action)
        if self.fail_action == action:
            from control_plane.hermes.lifecycle import HermesGatewayError

            raise HermesGatewayError(
                f"HERMES_GATEWAY_{action.upper()}_FAILED", "Gateway action failed."
            )
        self.running = action != "stop"
        return self.status()

    def restart(self) -> HermesGatewayStatus:
        self.actions.append("restart")
        if self.fail_action == "restart":
            from control_plane.hermes.lifecycle import HermesGatewayError

            raise HermesGatewayError("HERMES_GATEWAY_RESTART_FAILED", "Gateway restart failed.")
        self.running = True
        return self.status()

    def restore(self, prior: HermesGatewayStatus) -> HermesGatewayStatus:
        self.actions.append("restore")
        self.running = prior.running
        return self.status()


def _verify(token: str) -> dict:
    identities = {
        EXISTING_SECRET: {"id": 101, "username": "existing_bot"},
        CURRENT_SECRET: {"id": 202, "username": "current_bot"},
    }
    if token not in identities:
        raise ValueError("invalid credential")
    return identities[token]


@contextmanager
def _current_secret():
    yield CURRENT_SECRET


def _adapter(env_path: Path, gateway: FakeGateway, *, operator_user_id: int = 789):
    return HermesTelegramConfigurationAdapter(
        runner=FakeRunner(env_path),  # type: ignore[arg-type]
        gateway=gateway,  # type: ignore[arg-type]
        token_resolver=_current_secret,
        verify_token=_verify,
        binding_resolver=lambda _session_id: SimpleNamespace(operator_user_id=operator_user_id),
    )


def test_fresh_hermes_plan_writes_minimum_config_and_starts_gateway(tmp_path):
    env_path = tmp_path / "Hermes config" / ".env"
    gateway = FakeGateway(running=False)
    adapter = _adapter(env_path, gateway)

    readiness = adapter.inspect(proposed_token=CURRENT_SECRET, operator_user_id=789)
    assert readiness.configuration_status == "UNCONFIGURED"
    plan = adapter.create_plan(
        HermesTelegramConfigurationPlanRequest(binding_session_id="binding-complete")
    )
    result = adapter.execute_plan(plan.plan_id)

    text = env_path.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=" + CURRENT_SECRET in text
    assert "TELEGRAM_ALLOWED_USERS=789" in text
    assert "TELEGRAM_GROUP_ALLOWED_CHATS" not in text
    assert "ALLOW_ALL" not in text
    assert gateway.actions == ["start"]
    assert result["configuration_status"] == "SAME_BOT"
    assert CURRENT_SECRET not in repr(result)


@pytest.mark.parametrize(
    ("contents", "expected"),
    [
        (f"TELEGRAM_BOT_TOKEN={EXISTING_SECRET}\nTELEGRAM_ALLOWED_USERS=789\n", "DIFFERENT_BOT"),
        ("TELEGRAM_BOT_TOKEN=invalid\nTELEGRAM_ALLOWED_USERS=789\n", "INVALID_TOKEN"),
        (f"TELEGRAM_BOT_TOKEN={CURRENT_SECRET}\nTELEGRAM_ALLOWED_USERS=123\n", "PARTIAL"),
        (f"TELEGRAM_BOT_TOKEN={CURRENT_SECRET}\nTELEGRAM_ALLOWED_USERS=123,789\n", "SAME_BOT"),
    ],
)
def test_existing_configuration_state_matrix(tmp_path, contents, expected):
    env_path = tmp_path / ".env"
    env_path.write_text(contents, encoding="utf-8")
    adapter = _adapter(env_path, FakeGateway(running=True))
    result = adapter.inspect(proposed_token=CURRENT_SECRET, operator_user_id=789)
    assert result.configuration_status == expected
    assert CURRENT_SECRET not in result.model_dump_json()
    assert EXISTING_SECRET not in result.model_dump_json()


def test_readiness_uses_binding_operator_context_when_requested(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"TELEGRAM_BOT_TOKEN={CURRENT_SECRET}\nTELEGRAM_ALLOWED_USERS=789\n",
        encoding="utf-8",
    )
    adapter = _adapter(env_path, FakeGateway(running=True))

    without_context = adapter.readiness()
    with_context = adapter.readiness(binding_session_id="binding-complete")

    assert without_context.configuration_status == "PARTIAL"
    assert with_context.configuration_status == "SAME_BOT"
    assert with_context.operator_allowed is True


def test_different_bot_switch_requires_explicit_confirmation(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"TELEGRAM_BOT_TOKEN={EXISTING_SECRET}\nTELEGRAM_ALLOWED_USERS=789\n",
        encoding="utf-8",
    )
    adapter = _adapter(env_path, FakeGateway(running=True))
    with pytest.raises(InstallerError) as raised:
        adapter.create_plan(
            HermesTelegramConfigurationPlanRequest(
                binding_session_id="binding-complete",
                choice="switch_to_current",
            )
        )
    assert raised.value.code == "HERMES_TELEGRAM_CONFLICT_CONFIRMATION_REQUIRED"

    plan = adapter.create_plan(
        HermesTelegramConfigurationPlanRequest(
            binding_session_id="binding-complete",
            choice="switch_to_current",
            confirmation=True,
        )
    )
    result = adapter.execute_plan(plan.plan_id)
    assert result["bot_id"] == 202
    assert env_path.read_text(encoding="utf-8").count("TELEGRAM_BOT_TOKEN=") == 1


def test_same_bot_with_complete_allowlist_is_non_destructive(tmp_path):
    env_path = tmp_path / ".env"
    original = (
        "# keep this comment\n"
        f"TELEGRAM_BOT_TOKEN={CURRENT_SECRET}\n"
        "TELEGRAM_ALLOWED_USERS=123,789\n"
        "OTHER_SETTING=preserved\n"
    )
    env_path.write_text(original, encoding="utf-8")
    gateway = FakeGateway(running=True)
    adapter = _adapter(env_path, gateway)
    plan = adapter.create_plan(
        HermesTelegramConfigurationPlanRequest(binding_session_id="binding-complete")
    )
    adapter.execute_plan(plan.plan_id)
    assert env_path.read_text(encoding="utf-8") == original
    assert gateway.actions == []


def test_env_transaction_preserves_unknown_group_home_and_comments(tmp_path):
    env_path = tmp_path / "配置 with spaces" / ".env"
    env_path.parent.mkdir(parents=True)
    env_path.write_text(
        "# user comment\n"
        "OTHER_KEY=untouched\n"
        f"TELEGRAM_BOT_TOKEN={EXISTING_SECRET}\n"
        "TELEGRAM_ALLOWED_USERS=123, 456,123,not-a-number\n"
        "TELEGRAM_ALLOWED_USERS=456\n"
        "TELEGRAM_GROUP_ALLOWED_CHATS=-100123\n"
        "TELEGRAM_GROUP_ALLOWED_USERS=999\n"
        "TELEGRAM_HOME_CHANNEL=telegram:-100999\n",
        encoding="utf-8",
    )
    transaction = HermesEnvTransaction(env_path)
    receipt = transaction.update(token=CURRENT_SECRET, operator_user_id=789)
    updated = env_path.read_text(encoding="utf-8")

    assert updated.startswith("# user comment\nOTHER_KEY=untouched\n")
    assert updated.count("TELEGRAM_BOT_TOKEN=") == 1
    assert updated.count("TELEGRAM_ALLOWED_USERS=") == 1
    assert "TELEGRAM_ALLOWED_USERS=456,789" in updated
    assert "TELEGRAM_GROUP_ALLOWED_CHATS=-100123" in updated
    assert "TELEGRAM_GROUP_ALLOWED_USERS=999" in updated
    assert "TELEGRAM_HOME_CHANNEL=telegram:-100999" in updated
    assert not list(env_path.parent.glob("*.bak"))

    transaction.rollback(receipt)
    restored = env_path.read_text(encoding="utf-8")
    assert restored.count("TELEGRAM_ALLOWED_USERS=") == 2
    assert CURRENT_SECRET not in restored


def test_allowed_user_merge_is_numeric_unique_and_stable():
    assert merge_allowed_users("123, 456,123,*,invalid", 789) == "123,456,789"


def test_invalid_encoding_and_readonly_file_are_not_overwritten(tmp_path):
    invalid = tmp_path / "invalid.env"
    invalid.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(HermesEnvError) as encoding_error:
        HermesEnvTransaction(invalid).update(token=CURRENT_SECRET, operator_user_id=789)
    assert encoding_error.value.code == "HERMES_ENV_INVALID_ENCODING"
    assert invalid.read_bytes() == b"\xff\xfe\x00"

    readonly = tmp_path / "readonly.env"
    readonly.write_text("OTHER=value\n", encoding="utf-8")
    readonly.chmod(0o444)
    try:
        with pytest.raises(HermesEnvError) as permission_error:
            HermesEnvTransaction(readonly).update(token=CURRENT_SECRET, operator_user_id=789)
        assert permission_error.value.code == "HERMES_ENV_PERMISSION_DENIED"
    finally:
        readonly.chmod(0o644)
    assert readonly.read_text(encoding="utf-8") == "OTHER=value\n"


def test_symlink_is_refused_when_supported(tmp_path):
    target = tmp_path / "real.env"
    target.write_text("OTHER=value\n", encoding="utf-8")
    link = tmp_path / "linked.env"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("current Windows account cannot create symlinks")
    with pytest.raises(HermesEnvError) as raised:
        HermesEnvTransaction(link).inspect()
    assert raised.value.code == "HERMES_ENV_SYMLINK_UNSUPPORTED"


def test_atomic_replace_failure_leaves_original_and_no_temp_copy(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    original = b"OTHER=value\n"
    env_path.write_bytes(original)

    def fail_replace(_source, _target):
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(HermesEnvError) as raised:
        HermesEnvTransaction(env_path).update(token=CURRENT_SECRET, operator_user_id=789)
    assert raised.value.code == "HERMES_ENV_WRITE_FAILED"
    assert env_path.read_bytes() == original
    assert list(tmp_path.glob(".*.tmp")) == []


def test_gateway_failure_rolls_back_env_and_prior_state(tmp_path):
    env_path = tmp_path / ".env"
    original = f"TELEGRAM_BOT_TOKEN={EXISTING_SECRET}\nTELEGRAM_ALLOWED_USERS=789\n"
    env_path.write_text(original, encoding="utf-8")
    gateway = FakeGateway(running=True, fail_action="restart")
    adapter = _adapter(env_path, gateway)
    plan = adapter.create_plan(
        HermesTelegramConfigurationPlanRequest(
            binding_session_id="binding-complete",
            choice="switch_to_current",
            confirmation=True,
        )
    )
    with pytest.raises(Exception) as raised:
        adapter.execute_plan(plan.plan_id)
    assert CURRENT_SECRET not in str(raised.value)
    assert env_path.read_text(encoding="utf-8") == original
    assert gateway.running is True
    assert gateway.actions == ["restart", "restore"]


def test_existing_bot_adoption_and_credential_rollback_are_secret_free(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"TELEGRAM_BOT_TOKEN={EXISTING_SECRET}\nTELEGRAM_ALLOWED_USERS=789\n",
        encoding="utf-8",
    )
    adopted: list[str] = []
    rolled_back: list[bool] = []

    def adopt(token: str, _operation_id: str):
        adopted.append(token)

        def rollback() -> None:
            rolled_back.append(True)

        return rollback

    adapter = HermesTelegramConfigurationAdapter(
        runner=FakeRunner(env_path),  # type: ignore[arg-type]
        gateway=FakeGateway(running=True, fail_action="restart"),  # type: ignore[arg-type]
        token_resolver=_current_secret,
        verify_token=_verify,
        binding_resolver=lambda _session_id: SimpleNamespace(operator_user_id=789),
        credential_adopter=adopt,
    )
    plan = adapter.create_plan(
        HermesTelegramConfigurationPlanRequest(
            binding_session_id="binding-complete",
            choice="use_existing",
        )
    )
    with pytest.raises(OperationExecutionError) as raised:
        adapter.execute_plan(plan.plan_id, operation_id="adopt-op")
    assert raised.value.error.code == "HERMES_GATEWAY_RESTART_FAILED"
    assert adopted == [EXISTING_SECRET]
    assert rolled_back == [True]
    assert EXISTING_SECRET in env_path.read_text(encoding="utf-8")
    assert CURRENT_SECRET not in str(raised.value)


def test_credential_adopter_exception_is_sanitized(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"TELEGRAM_BOT_TOKEN={EXISTING_SECRET}\nTELEGRAM_ALLOWED_USERS=789\n",
        encoding="utf-8",
    )

    def broken_adopter(_token: str, _operation_id: str):
        raise RuntimeError(f"backend leaked {CURRENT_SECRET}")

    adapter = HermesTelegramConfigurationAdapter(
        runner=FakeRunner(env_path),  # type: ignore[arg-type]
        gateway=FakeGateway(running=True),  # type: ignore[arg-type]
        token_resolver=_current_secret,
        verify_token=_verify,
        binding_resolver=lambda _session_id: SimpleNamespace(operator_user_id=789),
        credential_adopter=broken_adopter,
    )
    plan = adapter.create_plan(
        HermesTelegramConfigurationPlanRequest(
            binding_session_id="binding-complete",
            choice="use_existing",
        )
    )
    with pytest.raises(OperationExecutionError) as raised:
        adapter.execute_plan(plan.plan_id)
    assert raised.value.error.code == "HERMES_CREDENTIAL_ADOPTION_FAILED"
    assert CURRENT_SECRET not in str(raised.value)


def test_update_lease_conflict_rolls_back_env_without_enum_shape_assumptions(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER=value\n", encoding="utf-8")

    class LeaseService:
        def get(self, _slot):
            return SimpleNamespace(owner=UpdateOwner.EXTERNAL, operation_id="external-op")

    adapter = HermesTelegramConfigurationAdapter(
        runner=FakeRunner(env_path),  # type: ignore[arg-type]
        gateway=FakeGateway(running=False),  # type: ignore[arg-type]
        token_resolver=_current_secret,
        verify_token=_verify,
        binding_resolver=lambda _session_id: SimpleNamespace(operator_user_id=789),
        lease_service=LeaseService(),
    )
    plan = adapter.create_plan(
        HermesTelegramConfigurationPlanRequest(binding_session_id="binding-complete")
    )
    with pytest.raises(OperationExecutionError) as raised:
        adapter.execute_plan(plan.plan_id)
    assert raised.value.error.code == "HERMES_GATEWAY_UPDATE_OWNER_CONFLICT"
    assert env_path.read_text(encoding="utf-8") == "OTHER=value\n"


def test_hermes_runtime_lease_is_handed_off_and_restored(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"TELEGRAM_BOT_TOKEN={CURRENT_SECRET}\nTELEGRAM_ALLOWED_USERS=789\n",
        encoding="utf-8",
    )
    gateway = FakeGateway(running=True)
    calls: list[str] = []
    lease = SimpleNamespace(
        owner=UpdateOwner.HERMES_RUNTIME,
        operation_id="runtime-op",
        credential_revision=3,
    )

    class LeaseService:
        def get(self, _slot):
            return lease

        def release(self, _slot, _operation_id, reason):
            calls.append("release:" + reason)
            return lease

        def acquire(self, _slot, owner, _operation_id, _revision, **_kwargs):
            calls.append("acquire:" + str(getattr(owner, "value", owner)))
            return lease

    adapter = HermesTelegramConfigurationAdapter(
        runner=FakeRunner(env_path),  # type: ignore[arg-type]
        gateway=gateway,  # type: ignore[arg-type]
        token_resolver=_current_secret,
        verify_token=_verify,
        binding_resolver=lambda _session_id: SimpleNamespace(operator_user_id=789),
        lease_service=LeaseService(),
    )
    plan = adapter.create_plan(
        HermesTelegramConfigurationPlanRequest(binding_session_id="binding-complete")
    )
    result = adapter.execute_plan(plan.plan_id)
    assert result["configuration_status"] == "SAME_BOT"
    assert gateway.actions == ["stop", "start"]
    assert calls == ["release:hermes_configuration_handoff", "acquire:hermes_runtime"]


def test_cli_runner_never_uses_shell_stdin_or_secret_argv(monkeypatch, tmp_path):
    executable = tmp_path / "hermes.exe"
    executable.write_bytes(b"synthetic")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="Hermes 1.0\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = HermesCliRunner(executable)
    result = runner.version()
    assert result.returncode == 0
    argv, options = calls[0]
    assert argv == [str(executable), "--version"]
    assert options["shell"] is False
    assert options["stdin"] is subprocess.DEVNULL
    assert options["creationflags"] in {0, 0x08000000}
    with pytest.raises(HermesCliError) as raised:
        runner.run("config", "set", "TELEGRAM_BOT_TOKEN", CURRENT_SECRET)
    assert raised.value.code == "HERMES_SECRET_ARGV_FORBIDDEN"
    assert CURRENT_SECRET not in str(raised.value)
    assert len(calls) == 1


def test_cli_capabilities_probe_help_without_mutating_gateway(monkeypatch, tmp_path):
    executable = tmp_path / "hermes.exe"
    executable.write_bytes(b"synthetic")
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        args = argv[1:]
        if args == ["--version"]:
            return subprocess.CompletedProcess(argv, 0, stdout="0.20.0\n", stderr="")
        if args == ["config", "env-path"]:
            return subprocess.CompletedProcess(argv, 0, stdout=str(tmp_path / ".env"), stderr="")
        if args == ["gateway", "--help"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout="Commands: status start stop restart install\n", stderr=""
            )
        raise AssertionError(args)

    monkeypatch.setattr(subprocess, "run", fake_run)
    capabilities = HermesCliRunner(executable).capabilities()
    assert capabilities["installed"] is True
    assert capabilities["env_path"] is True
    assert all(
        capabilities[f"gateway_{action}"] is True
        for action in ("status", "start", "stop", "restart")
    )
    assert not any(
        call[1:] in (["gateway", "start"], ["gateway", "stop"], ["gateway", "restart"])
        for call in calls
    )


class LifecycleRunner:
    def __init__(self, results: list[HermesCommandResult]) -> None:
        self.results = iter(results)
        self.actions: list[str] = []

    def gateway(self, action: str) -> HermesCommandResult:
        self.actions.append(action)
        return next(self.results)


def test_gateway_status_does_not_misread_not_running_as_running():
    lifecycle = HermesGatewayLifecycle(
        LifecycleRunner([HermesCommandResult(0, "Gateway is not running", "")])  # type: ignore[arg-type]
    )
    status = lifecycle.status()
    assert status.state == "stopped"
    assert status.running is False

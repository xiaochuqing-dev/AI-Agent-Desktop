from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from control_plane.domain.models import (
    CredentialStatus,
    DryRunAction,
    DryRunActionType,
    DryRunPlan,
    EstimatedRisk,
    ReadinessReport,
    SecretRef,
)


def _action(component_id="hermes") -> DryRunAction:
    return DryRunAction(
        action_id=f"act-{component_id}",
        component_id=component_id,
        action_type=DryRunActionType.INSTALL,
        reason="未安装",
        prerequisites=[],
        requires_admin=True,
        requires_user_interaction=True,
        secret_required=False,
        estimated_risk=EstimatedRisk.MEDIUM,
        reversible=True,
        rollback_hint="卸载",
    )


def test_dryrun_plan_execute_always_false():
    plan = DryRunPlan(
        plan_id="plan-1",
        operation_id="op-1",
        actions=[_action()],
        generated_at=datetime.now(UTC),
    )
    assert plan.execute is False
    assert plan.status == "planned"
    assert plan.actions[0].status == "planned"


def test_dryrun_action_rejects_extra_fields():
    with pytest.raises(ValidationError):
        DryRunAction(
            action_id="a",
            component_id="c",
            action_type=DryRunActionType.START,
            reason="r",
            prerequisites=[],
            requires_admin=False,
            requires_user_interaction=False,
            secret_required=False,
            estimated_risk=EstimatedRisk.LOW,
            reversible=True,
            rollback_hint="",
            status="planned",
            unexpected="x",
        )


def test_secret_ref_never_carries_value():
    ref = SecretRef(
        secret_ref_id="sr-1",
        credential_ref="cred-1",
        purpose="telegram_bot_token",
        owner="application",
        backend="windows_credential_manager",
        status=CredentialStatus.STORED,
        exists=True,
    )
    assert ref.redacted is True
    assert not hasattr(ref, "value")


def test_readiness_report_system_modified_false():
    from datetime import datetime

    plan = DryRunPlan(
        plan_id="p",
        operation_id="o",
        actions=[_action()],
        generated_at=datetime.now(UTC),
    )
    rpt = ReadinessReport(
        report_id="r",
        scan_operation_id="o",
        user_summary="ok",
        dry_run_plan=plan,
        scanned_at=datetime.now(UTC),
        scan_version="0.1.0",
    )
    assert rpt.system_modified is False
    assert rpt.redaction_applied is True

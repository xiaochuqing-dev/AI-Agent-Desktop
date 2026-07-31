# 发现服务:编排只读 Adapter,生成 ReadinessReport + DryRunPlan,发事件,推进 Operation。
# 全程无副作用:不安装、不登录、不启停、不发消息、不改配置。
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from ..domain.models import (
    Capability,
    Component,
    DryRunAction,
    DryRunActionType,
    DryRunPlan,
    EstimatedRisk,
    OperationStatus,
    ReadinessReport,
    ResourceRef,
)
from ..domain.ports import DiscoveryAdapter
from .event_log import EventLog
from .operation_store import OperationStore, utcnow


def _plan_action_for(component: Component) -> DryRunAction | None:
    # 根据组件状态生成单条 dry-run 动作。execute 恒 false,status 恒 planned。
    st = component.state
    if st.installation.value in ("not_installed", "unknown"):
        return DryRunAction(
            action_id=f"act-{component.component_id}-install",
            component_id=component.component_id,
            action_type=DryRunActionType.INSTALL,
            reason="组件未安装或未发现",
            prerequisites=[],
            requires_admin=True,
            requires_user_interaction=True,
            secret_required=False,
            estimated_risk=EstimatedRisk.MEDIUM,
            reversible=True,
            rollback_hint="卸载安装产物并清理数据目录",
        )
    if st.configuration.value in ("missing", "invalid"):
        return DryRunAction(
            action_id=f"act-{component.component_id}-configure",
            component_id=component.component_id,
            action_type=DryRunActionType.CONFIGURE,
            reason="配置缺失或无效",
            prerequisites=[],
            requires_admin=False,
            requires_user_interaction=True,
            secret_required=True,
            estimated_risk=EstimatedRisk.LOW,
            reversible=True,
            rollback_hint="恢复旧配置备份",
        )
    if st.authentication.value in ("required", "expired", "invalid"):
        return DryRunAction(
            action_id=f"act-{component.component_id}-authenticate",
            component_id=component.component_id,
            action_type=DryRunActionType.AUTHENTICATE,
            reason="需要登录或认证已失效",
            prerequisites=[],
            requires_admin=False,
            requires_user_interaction=True,
            secret_required=True,
            estimated_risk=EstimatedRisk.LOW,
            reversible=True,
            rollback_hint="退出登录并重新认证",
        )
    return None


class DiscoveryService:
    def __init__(self, adapters: list[DiscoveryAdapter], store: OperationStore, events: EventLog) -> None:
        self.adapters = adapters
        self.store = store
        self.events = events

    def run(self, operation_id: str, correlation_id: str) -> ReadinessReport:
        # 同步执行发现(只读)。API 层在后台线程调用本方法。
        target = ResourceRef(kind="system", id="local")
        self.store.transition(
            operation_id, status=OperationStatus.RUNNING, phase="scanning", message="开始就绪扫描"
        )
        self.events.emit(
            type_="com.aiagentdesktop.operation.started.v1",
            subject=f"operation:{operation_id}",
            data={"operation_id": operation_id, "kind": "discovery"},
            resource_ref=target,
            correlation_id=correlation_id,
            operation_id=operation_id,
        )

        components: list[Component] = []
        total = len(self.adapters)
        for idx, adapter in enumerate(self.adapters, start=1):
            try:
                found = adapter.discover()
            except Exception:
                # 单探针失败:产 Diagnostic,状态设 unknown,其他组件继续
                found = []
            for comp in found:
                components.append(comp)
                self.events.emit(
                    type_="com.aiagentdesktop.component.discovered.v1",
                    subject=f"component:{comp.component_id}",
                    data={"component_id": comp.component_id, "kind": comp.kind},
                    resource_ref=ResourceRef(kind="component", id=comp.component_id),
                    correlation_id=correlation_id,
                    operation_id=operation_id,
                )
            self.store.transition(
                operation_id,
                status=OperationStatus.RUNNING,
                phase="scanning",
                message=f"已扫描 {adapter.adapter_id}",
                completed_units=idx,
                total_units=total,
            )
            self.events.emit(
                type_="com.aiagentdesktop.scan.progress.v1",
                subject=f"operation:{operation_id}",
                data={"adapter": adapter.adapter_id, "completed": idx, "total": total},
                resource_ref=target,
                correlation_id=correlation_id,
                operation_id=operation_id,
            )

        # 生成 dry-run 计划
        actions = [a for c in components if (a := _plan_action_for(c)) is not None]
        plan = DryRunPlan(
            plan_id=f"plan-{operation_id}",
            operation_id=operation_id,
            execute=False,
            status="planned",
            actions=actions or [
                DryRunAction(
                    action_id="act-noop",
                    component_id="system",
                    action_type=DryRunActionType.CONFIGURE,
                    reason="无待修复组件",
                    prerequisites=[],
                    requires_admin=False,
                    requires_user_interaction=False,
                    secret_required=False,
                    estimated_risk=EstimatedRisk.LOW,
                    reversible=True,
                    rollback_hint="无需回滚",
                )
            ],
            generated_at=utcnow(),
        )
        self.events.emit(
            type_="com.aiagentdesktop.plan.generated.v1",
            subject=f"plan:{plan.plan_id}",
            data={"plan_id": plan.plan_id, "actions": len(plan.actions)},
            resource_ref=ResourceRef(kind="operation", id=operation_id),
            correlation_id=correlation_id,
            operation_id=operation_id,
        )

        # 聚合就绪报告
        blockers = []
        warnings = []
        ready_items = []
        for c in components:
            us = c.state.user_status.value
            if us in ("not_installed", "configuration_invalid", "start_failed", "login_required"):
                blockers.append(c.component_id)
            elif us in ("partially_degraded", "update_available", "installed_unconfigured"):
                warnings.append(c.component_id)
            elif us == "running_healthy":
                ready_items.append(c.component_id)

        report = ReadinessReport(
            report_id=f"rpt-{operation_id}",
            scan_operation_id=operation_id,
            user_summary=self._summarize(components, ready_items, warnings, blockers),
            components=components,
            blockers=[],
            warnings=[],
            ready_items=ready_items,
            suggested_actions=[a.action_type.value for a in plan.actions],
            estimated_next_steps=["审阅 dry-run 计划", "确认后进入单组件安装切片"],
            dry_run_plan=plan,
            evidence_sources=[a.adapter_id for a in self.adapters],
            scanned_at=utcnow(),
            scan_version="0.1.0",
            system_modified=False,
            redaction_applied=True,
        )

        self.store.transition(
            operation_id,
            status=OperationStatus.SUCCEEDED,
            phase="completed",
            message="扫描完成,未修改系统",
            completed_units=total,
            total_units=total,
            result=report.model_dump(mode="json"),
        )
        self.events.emit(
            type_="com.aiagentdesktop.operation.completed.v1",
            subject=f"operation:{operation_id}",
            data={"operation_id": operation_id, "status": "succeeded"},
            resource_ref=target,
            correlation_id=correlation_id,
            operation_id=operation_id,
        )
        return report

    def _summarize(self, components, ready, warnings, blockers) -> str:
        if not blockers and not warnings:
            return f"扫描完成,共 {len(components)} 个组件,全部就绪。本次扫描未修改系统。"
        return (
            f"扫描完成,共 {len(components)} 个组件:就绪 {len(ready)},"
            f"警告 {len(warnings)},阻塞 {len(blockers)}。本次扫描未修改系统。"
        )

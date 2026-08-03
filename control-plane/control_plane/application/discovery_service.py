# 发现服务:编排只读 Adapter,生成 ReadinessReport + DryRunPlan,发事件,推进 Operation。
# 全程无副作用:不安装、不登录、不启停、不发消息、不改配置。
from __future__ import annotations

from ..domain.models import (
    Component,
    Diagnostic,
    DiagnosticSeverity,
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

OPTIONAL_COMPONENT_IDS = {"cc-switch"}


def _plan_action_for(component: Component) -> DryRunAction | None:
    # 根据组件状态生成单条 dry-run 动作。execute 恒 false,status 恒 planned。
    st = component.state
    if st.installation.value == "not_installed":
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


def _diagnostic(
    *,
    operation_id: str,
    correlation_id: str,
    target_kind: str,
    target_id: str,
    severity: DiagnosticSeverity,
    code: str,
    summary: str,
    user_message: str,
    suggested_actions: list[str],
    technical_details: dict,
) -> Diagnostic:
    safe_code = code.lower().replace("_", "-")
    return Diagnostic(
        diagnostic_id=f"diag-{operation_id}-{target_id}-{safe_code}"[:128],
        severity=severity,
        code=code,
        summary=summary,
        user_message=user_message,
        suggested_actions=suggested_actions,
        technical_details=technical_details,
        redaction_applied=True,
        created_at=utcnow(),
        correlation_id=correlation_id,
        operation_id=operation_id,
        target_ref=ResourceRef(kind=target_kind, id=target_id),
    )


def _component_details(component: Component) -> dict:
    state = component.state
    return {
        "component_id": component.component_id,
        "observed_states": {
            "installation": state.installation.value,
            "configuration": state.configuration.value,
            "authentication": state.authentication.value,
            "runtime": state.runtime.value,
            "health": state.health.value,
            "update": state.update.value,
        },
        "evidence_reasons": [condition.reason for condition in state.conditions],
    }


def _diagnostics_for_component(
    component: Component, operation_id: str, correlation_id: str
) -> tuple[list[Diagnostic], list[Diagnostic]]:
    blockers: list[Diagnostic] = []
    warnings: list[Diagnostic] = []
    state = component.state
    details = _component_details(component)

    def add(
        severity: DiagnosticSeverity,
        code: str,
        summary: str,
        user_message: str,
        actions: list[str],
    ) -> None:
        item = _diagnostic(
            operation_id=operation_id,
            correlation_id=correlation_id,
            target_kind="component",
            target_id=component.component_id,
            severity=severity,
            code=code,
            summary=summary,
            user_message=user_message,
            suggested_actions=actions,
            technical_details=details,
        )
        (blockers if severity == DiagnosticSeverity.ERROR else warnings).append(item)

    if state.installation.value == "not_installed":
        if component.component_id in OPTIONAL_COMPONENT_IDS:
            add(
                DiagnosticSeverity.WARNING,
                "OPTIONAL_COMPONENT_NOT_INSTALLED",
                f"可选组件 {component.display_name} 未安装",
                f"未发现可选组件 {component.display_name}，不会阻断核心链路。",
                ["需要该可选入口时再按受控安装流程处理"],
            )
        else:
            add(
                DiagnosticSeverity.ERROR,
                "COMPONENT_NOT_INSTALLED",
                f"必需组件 {component.display_name} 未安装",
                f"未发现 {component.display_name}，相关能力当前不可用。",
                ["审阅 dry-run 安装计划", "确认来源和版本后再安装"],
            )
        return blockers, warnings

    if state.installation.value in ("unknown", "failed"):
        add(
            DiagnosticSeverity.WARNING,
            "COMPONENT_INSTALLATION_UNVERIFIED",
            f"{component.display_name} 安装状态无法确认",
            "只读探测没有获得足够证据，未将组件判断为已安装或健康。",
            ["重新运行只读发现", "检查受支持的安装来源"],
        )

    if state.configuration.value == "missing":
        add(
            DiagnosticSeverity.WARNING,
            "COMPONENT_CONFIGURATION_MISSING",
            f"{component.display_name} 配置缺失",
            "未发现所需配置资料，尚不能确认组件可用。",
            ["审阅 dry-run 配置计划", "在后续受控阶段补充配置"],
        )
    elif state.configuration.value in ("invalid", "conflict"):
        add(
            DiagnosticSeverity.ERROR,
            "COMPONENT_CONFIGURATION_INVALID",
            f"{component.display_name} 配置无效或冲突",
            "配置校验未通过，必须先修复配置或唯一管理权冲突。",
            ["查看脱敏诊断", "选择唯一 ManagementOwner 后重新校验"],
        )

    if state.authentication.value in ("required", "expired", "invalid"):
        add(
            DiagnosticSeverity.ERROR,
            "COMPONENT_AUTHENTICATION_REQUIRED",
            f"{component.display_name} 需要认证",
            "认证缺失或已失效，相关能力当前不可用。",
            ["使用官方登录入口或受控凭据流程完成认证"],
        )

    if state.runtime.value == "failed":
        add(
            DiagnosticSeverity.ERROR,
            "COMPONENT_RUNTIME_FAILED",
            f"{component.display_name} 运行状态失败",
            "检测到运行失败证据，当前不能将组件报告为可用。",
            ["查看脱敏诊断", "在受控阶段执行恢复"],
        )
    elif state.runtime.value == "stopped":
        add(
            DiagnosticSeverity.WARNING,
            "COMPONENT_RUNTIME_STOPPED",
            f"{component.display_name} 当前已停止",
            "组件已安装但没有运行，不能将其报告为运行正常。",
            ["在后续受控阶段确认后启动"],
        )

    if state.health.value == "unhealthy":
        add(
            DiagnosticSeverity.ERROR,
            "COMPONENT_HEALTH_UNHEALTHY",
            f"{component.display_name} 健康检查失败",
            "直接健康证据表明组件当前不可用。",
            ["查看脱敏诊断并按建议恢复"],
        )
    elif state.health.value == "degraded":
        add(
            DiagnosticSeverity.WARNING,
            "COMPONENT_HEALTH_DEGRADED",
            f"{component.display_name} 部分能力异常",
            "组件仍有可用能力，但直接健康证据显示部分异常。",
            ["查看受影响能力并重新检查"],
        )

    if state.update.value == "update_available":
        add(
            DiagnosticSeverity.WARNING,
            "COMPONENT_UPDATE_AVAILABLE",
            f"{component.display_name} 有可用更新",
            "检测到更新，但本阶段不会自动升级。",
            ["在建立快照和回滚点后再评估更新"],
        )

    unknown_dimensions = [
        name for name, value in details["observed_states"].items() if value == "unknown"
    ]
    if unknown_dimensions:
        unknown_details = dict(details)
        unknown_details["unknown_dimensions"] = unknown_dimensions
        details = unknown_details
        add(
            DiagnosticSeverity.WARNING,
            "COMPONENT_STATE_UNVERIFIED",
            f"{component.display_name} 部分状态未验证",
            "只读证据不足，未知状态不会被自动视为正常。",
            ["重新运行只读发现", "在后续阶段执行无副作用验证"],
        )

    return blockers, warnings


def _adapter_failure_diagnostic(
    adapter: DiscoveryAdapter, operation_id: str, correlation_id: str
) -> Diagnostic:
    return _diagnostic(
        operation_id=operation_id,
        correlation_id=correlation_id,
        target_kind="adapter",
        target_id=adapter.adapter_id,
        severity=DiagnosticSeverity.WARNING,
        code="ADAPTER_DISCOVERY_FAILED",
        summary=f"{adapter.adapter_id} 只读发现失败",
        user_message="单个发现探针失败，其他组件仍已继续扫描；该探针状态保持未知。",
        suggested_actions=["重新运行只读发现", "检查该 Adapter 的受支持依赖"],
        technical_details={"adapter_id": adapter.adapter_id, "state": "unknown"},
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


class DiscoveryService:
    def __init__(
        self, adapters: list[DiscoveryAdapter], store: OperationStore, events: EventLog
    ) -> None:
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
        adapter_warnings: list[Diagnostic] = []
        total = len(self.adapters)
        for idx, adapter in enumerate(self.adapters, start=1):
            try:
                found = adapter.discover()
            except Exception:
                # 不暴露异常、堆栈或私有路径；用结构化 Diagnostic 表达 unknown。
                found = []
                adapter_warnings.append(
                    _adapter_failure_diagnostic(adapter, operation_id, correlation_id)
                )
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

        # 聚合结构化 Diagnostic。未知状态不计为健康。
        blockers: list[Diagnostic] = []
        warnings: list[Diagnostic] = list(adapter_warnings)
        ready_items: list[str] = []
        for component in components:
            component_blockers, component_warnings = _diagnostics_for_component(
                component, operation_id, correlation_id
            )
            blockers.extend(component_blockers)
            warnings.extend(component_warnings)
            state = component.state
            if (
                state.user_status.value == "running_healthy"
                and state.runtime.value == "running"
                and state.health.value == "healthy"
            ):
                ready_items.append(component.component_id)

        # 生成 dry-run 计划
        actions = [a for c in components if (a := _plan_action_for(c)) is not None]
        no_action_reason = (
            "尚无可执行修复动作；请先审阅诊断并完成只读复核"
            if blockers or warnings
            else "无待修复组件"
        )
        plan = DryRunPlan(
            plan_id=f"plan-{operation_id}",
            operation_id=operation_id,
            execute=False,
            status="planned",
            actions=actions
            or [
                DryRunAction(
                    action_id="act-noop",
                    component_id="system",
                    action_type=DryRunActionType.CONFIGURE,
                    reason=no_action_reason,
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

        suggested_actions = _unique(
            [
                action
                for diagnostic in [*blockers, *warnings]
                for action in diagnostic.suggested_actions
            ]
        )

        report = ReadinessReport(
            report_id=f"rpt-{operation_id}",
            scan_operation_id=operation_id,
            user_summary=self._summarize(components, ready_items, warnings, blockers),
            components=components,
            blockers=blockers,
            warnings=warnings,
            ready_items=ready_items,
            suggested_actions=suggested_actions or ["保持当前状态并定期重新扫描"],
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
        if not blockers and not warnings and len(ready) == len(components):
            return f"扫描完成,共 {len(components)} 个组件,全部就绪。本次扫描未修改系统。"
        return (
            f"扫描完成,共 {len(components)} 个组件:就绪 {len(ready)},"
            f"警告 {len(warnings)},阻塞 {len(blockers)}。本次扫描未修改系统。"
        )

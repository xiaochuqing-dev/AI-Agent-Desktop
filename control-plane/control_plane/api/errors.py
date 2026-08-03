# 结构化错误:problem+json + 稳定 code。Secret、堆栈、私有路径不出现。
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Problem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = "urn:ai-agent-desktop:error:internal"
    title: str = Field(min_length=1, max_length=256)
    status: int = Field(ge=400, le=599)
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    detail: str = Field(max_length=2048)
    user_message: str = Field(min_length=1, max_length=2048)
    retryable: bool
    recovery_actions: list[str] = Field(default_factory=list)
    diagnostic_id: str | None = None
    operation_id: str | None = None
    correlation_id: str = "default"


class ControlPlaneError(Exception):
    # 抛出后被异常处理器转为 problem+json。
    def __init__(
        self,
        *,
        code: str,
        title: str,
        status: int,
        detail: str,
        user_message: str,
        retryable: bool = False,
        recovery_actions: list[str] | None = None,
        correlation_id: str = "default",
        diagnostic_id: str | None = None,
        operation_id: str | None = None,
    ) -> None:
        self.problem = Problem(
            code=code,
            title=title,
            status=status,
            detail=detail,
            user_message=user_message,
            retryable=retryable,
            recovery_actions=recovery_actions or [],
            correlation_id=correlation_id,
            diagnostic_id=diagnostic_id,
            operation_id=operation_id,
        )
        super().__init__(detail)


def capability_unsupported(
    component_id: str, action: str, correlation_id: str = "default"
) -> ControlPlaneError:
    # 首片不实现 lifecycle/credentials/owner 真实写入;统一返回 CAPABILITY_UNSUPPORTED。
    return ControlPlaneError(
        code="CAPABILITY_UNSUPPORTED",
        title="Capability unsupported",
        status=501,
        detail=f"动作 {action} 对组件 {component_id} 在本切片未实现。",
        user_message="当前阶段尚未实现该操作,请等待后续切片。",
        retryable=False,
        recovery_actions=["wait_for_next_phase"],
        correlation_id=correlation_id,
    )

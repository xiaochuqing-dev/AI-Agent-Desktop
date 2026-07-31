# 领域端口(抽象接口)。核心只依赖这些接口,不依赖具体 Adapter 实现。
# Adapter 依赖核心契约,核心不反向依赖 Adapter。
from __future__ import annotations

from abc import ABC, abstractmethod

from .models import Capability, Component, CredentialMetadata, Diagnostic, SecretRef


class DiscoveryAdapter(ABC):
    # 只读发现 Adapter:把外部真实状态映射为通用 Component 模型。
    # 禁止:编排多 Agent、发消息、执行任务、写第三方配置、自动登录、修改现有服务。
    adapter_id: str
    component_kinds: list[str]

    @abstractmethod
    def discover(self) -> list[Component]:
        # 发现失败时返回 not_installed/unknown 状态的 Component,不抛底层异常。
        ...

    @abstractmethod
    def capabilities(self) -> list[Capability]:
        # 声明本 Adapter 真实能力等级,不得补齐上游不具备的能力。
        ...


class HealthProbe(ABC):
    # 无副作用健康探针:进程身份、受限端点、依赖、版本等。不发外部消息。
    @abstractmethod
    def probe_health(self, component_id: str, depth: str) -> Diagnostic:
        ...


class CredentialProvider(ABC):
    # 凭据提供者接口(本阶段冻结)。首片只实现只读判断,不实现真实写入与使用。
    backend_name: str

    @abstractmethod
    def list_metadata(self) -> list[CredentialMetadata]:
        # 只列脱敏元数据,不含值或值片段。
        ...

    @abstractmethod
    def has_reference(self, secret_ref: SecretRef) -> bool | None:
        # 判断引用是否存在或可访问。无法判断时返回 None,不读取明文。
        ...


class LifecycleProvider(ABC):
    # 生命周期端口。首片只生成 shadow plan,不执行 start/stop/restart。
    @abstractmethod
    def shadow_plan(self, component_id: str) -> list[dict]:
        # 识别现有启动所有者、目标进程、依赖、命令与预期结果,只生成计划不执行。
        ...

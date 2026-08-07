# FastAPI 应用:loopback、Bearer、problem+json、SSE 与模块化管理路由。
# 已实现 cc-connect 隔离安装、非敏感配置事务、显式所有权和产品进程生命周期。
# 真实 Credential、Telegram 绑定及其他组件写操作仍保持 unsupported。
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..adapters.discovery import default_adapters
from ..application.discovery_service import DiscoveryService
from ..application.event_log import CursorExpired, EventLog
from ..application.operation_store import (
    IdempotencyKeyReuse,
    OperationStore,
    body_digest,
)
from ..cc_connect import (
    CcConnectExternalDetector,
    CcConnectNativeConfigurationService,
    RuntimeSecretInjector,
)
from ..configuration.service import CcConnectConfigurationService
from ..credentials.service import CredentialService
from ..credentials.windows_backend import CredentialBackendError, SecretBackend
from ..domain.models import (
    Capability,
    Component,
    Diagnostic,
    DiagnosticSeverity,
    Operation,
    OperationStatus,
    ReadinessReport,
    ResourceRef,
    SystemInfo,
)
from ..external_tools.cc_switch import CcSwitchExternalToolProvider
from ..hermes import HermesConfigurationPlanner
from ..infrastructure.config import Settings
from ..installer.artifacts import InstallerError
from ..installer.models import (
    InstallConfirmationRequest,
    InstallPlan,
    InstallPlanRequest,
    ManagedVersion,
    OperationAuditEvent,
    RestoreRequest,
    UninstallRequest,
)
from ..installer.service import CcConnectInstaller
from ..installer.version_store import ManagedVersionStore
from ..lifecycle.managed_process import ManagedProcessService
from ..lifecycle.models import LifecycleActionRequest
from ..lifecycle.port_ownership import PortOwnershipInspector
from ..network.proxy import ProxyPolicy
from ..observability.service import LiveE2ETestService
from ..operations import (
    ExecutionContext,
    OperationExecutionError,
    OperationExecutor,
    RecoveryDecision,
)
from ..persistence.models import DiagnosticRecord, IdempotencyRecord
from ..persistence.session import Database
from ..security.redaction import redact_value
from ..telegram.api_client import TelegramBotApiClient
from ..telegram.binding_service import TelegramBindingService
from ..telegram.bot_identity import TelegramBotIdentityService
from ..telegram.update_lease import TelegramUpdateLeaseService
from ..updates.providers import CcConnectArtifactProvider, HermesUpdateProvider
from .errors import ControlPlaneError, Problem, capability_unsupported
from .routers import (
    build_configuration_router,
    build_credentials_router,
    build_integrations_router,
    build_lifecycle_router,
    build_native_configuration_router,
    build_observability_router,
    build_telegram_router,
)


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=512)


class AppState:
    def __init__(
        self,
        settings: Settings,
        adapters: list | None = None,
        installer_fault_injector=None,
        credential_backend: SecretBackend | None = None,
        telegram_client: TelegramBotApiClient | None = None,
        hermes_path_lookup=None,
    ) -> None:
        self.settings = settings
        self.db = Database(settings)
        self.events = EventLog()
        if adapters is None:
            self.registry = default_adapters()
        else:
            # 测试注入 Fake Adapter,避免扫描真实运行环境
            from ..adapters import AdapterRegistry

            reg = AdapterRegistry()
            for a in adapters:
                reg.register(a)
            self.registry = reg
        self.installer = CcConnectInstaller(
            settings,
            self.db,
            self.events,
            fault_injector=installer_fault_injector,
        )
        self.version_store = ManagedVersionStore(self.installer.layout, self.db)
        self.port_inspector = PortOwnershipInspector()
        self.configuration = CcConnectConfigurationService(
            self.db,
            self.installer.layout,
            version_store=self.version_store,
            port_inspector=self.port_inspector,
        )
        self.credentials = CredentialService(self.db, credential_backend)

        def resolve_proxy_credential(reference_id: str) -> str:
            with self.credentials.resolve_for_operation(reference_id) as value:
                return value

        self.telegram_client = telegram_client or TelegramBotApiClient(
            proxy_policy=ProxyPolicy(
                mode=settings.telegram_proxy_mode,  # type: ignore[arg-type]
                explicit_url=settings.telegram_proxy_url,
                credential_reference_id=settings.telegram_proxy_credential_reference,
            ),
            proxy_secret_resolver=resolve_proxy_credential,
        )
        self.telegram_identities = TelegramBotIdentityService(
            self.db,
            self.credentials,
            self.telegram_client,
        )
        self.telegram_leases = TelegramUpdateLeaseService(self.db)
        self.telegram_binding = TelegramBindingService(
            self.db,
            self.credentials,
            self.telegram_identities,
            self.telegram_leases,
            self.telegram_client,
        )
        self.native_configuration = CcConnectNativeConfigurationService(
            self.db,
            self.installer.layout,
            self.credentials,
            self.telegram_identities,
            self.telegram_binding,
            self.configuration,
            version_store=self.version_store,
        )
        self.runtime_secrets = RuntimeSecretInjector(self.db, self.credentials)
        self.cc_connect_external = CcConnectExternalDetector(
            self.installer.layout.root,
            port_inspector=self.port_inspector,
        )
        self.lifecycle = ManagedProcessService(
            self.db,
            self.installer.layout,
            self.configuration,
            version_store=self.version_store,
            port_inspector=self.port_inspector,
            native_configuration_service=self.native_configuration,
            runtime_secret_injector=self.runtime_secrets,
            telegram_identities=self.telegram_identities,
            telegram_leases=self.telegram_leases,
            external_state_detector=self.cc_connect_external,
            startup_timeout_seconds=settings.lifecycle_startup_timeout_seconds,
            stop_timeout_seconds=settings.lifecycle_stop_timeout_seconds,
            stable_window_seconds=settings.lifecycle_stable_window_seconds,
        )
        self.observability = LiveE2ETestService(
            self.db,
            credentials=self.credentials,
            identities=self.telegram_identities,
            binding=self.telegram_binding,
            lifecycle=self.lifecycle,
            configuration=self.configuration,
            telegram_client=self.telegram_client,
        )
        self.cc_connect_updates = CcConnectArtifactProvider(self.db, self.version_store)
        self.hermes_updates = HermesUpdateProvider()
        self.hermes_configuration = HermesConfigurationPlanner(
            self.db,
            self.telegram_binding,
            path_lookup=hermes_path_lookup,
        )
        self.cc_switch = CcSwitchExternalToolProvider(self.db)
        self.executor = OperationExecutor(
            self.db,
            worker_count=settings.operation_worker_count,
            queue_capacity=settings.operation_queue_capacity,
            shutdown_timeout_seconds=settings.operation_shutdown_timeout_seconds,
        )
        self._register_handlers()
        self.started_at = datetime.now(UTC)
        self.instance_id = f"cp-{uuid.uuid4().hex[:12]}"

    def start(self) -> None:
        self.installer.recover_interrupted_operations()
        self.lifecycle.recover_leases()
        self.executor.start()
        # Executor recovery first classifies interrupted jobs; service cleanup then
        # rolls back any newly terminal installer operation and releases stale leases.
        self.installer.recover_interrupted_operations()
        self.lifecycle.recover_leases()
        try:
            self.lifecycle.reconcile(operation_id="control-plane-startup")
        except InstallerError:
            # Startup remains available for diagnostics even when managed state is corrupt.
            pass

    def stop(self) -> bool:
        stopped = self.executor.shutdown()
        # Release SQLite/WAL handles when the embedded server exits; this is
        # required for ordinary-user candidate cleanup on Windows.
        self.db.engine.dispose()
        return stopped

    def _register_handlers(self) -> None:
        self.executor.register(
            "discovery",
            self._execute_discovery,
            recovery_probe=lambda _operation_id, _payload: RecoveryDecision.requeue(),
        )
        self.executor.register(
            "cc_connect_install",
            self._execute_install,
            recovery_probe=self._installer_recovery_probe,
        )
        self.executor.register(
            "cc_connect_uninstall",
            self._execute_uninstall,
            recovery_probe=self._installer_recovery_probe,
        )
        self.executor.register(
            "cc_connect_restore",
            self._execute_restore,
            recovery_probe=self._installer_recovery_probe,
        )
        self.executor.register(
            "cc_connect_configuration_apply",
            self._execute_configuration,
            recovery_probe=self.configuration.recovery_probe,
        )
        self.executor.register(
            "cc_connect_native_configuration_apply",
            self._execute_native_configuration,
            recovery_probe=self.native_configuration.recovery_probe,
        )
        self.executor.register(
            "telegram_bot_verify",
            self._execute_telegram_bot_verify,
            recovery_probe=lambda _operation_id, _payload: RecoveryDecision.requeue(),
        )
        self.executor.register(
            "telegram_webhook_delete",
            self._execute_telegram_webhook_delete,
            recovery_probe=lambda _operation_id, _payload: RecoveryDecision.fail(
                code="TELEGRAM_WEBHOOK_DELETE_RECOVERY_REQUIRES_RECONFIRMATION"
            ),
        )
        self.executor.register(
            "telegram_binding_poll",
            self.telegram_binding.poll,
            recovery_probe=self.telegram_binding.recovery_probe,
        )
        self.executor.register(
            "cc_connect_ownership_handoff",
            self._execute_ownership_handoff,
            recovery_probe=self.lifecycle.recovery_probe,
        )
        for action in ("start", "stop", "restart", "reconcile", "health"):
            self.executor.register(
                f"cc_connect_lifecycle_{action}",
                self._execute_lifecycle,
                recovery_probe=self.lifecycle.recovery_probe,
            )

    def _execute_discovery(self, context: ExecutionContext) -> None:
        with self.db.session() as session:
            service = DiscoveryService(self.registry.all(), OperationStore(session), self.events)
            service.run(
                context.operation_id,
                str(context.payload.get("correlation_id", "executor")),
            )

    def _execute_install(self, context: ExecutionContext) -> None:
        self.installer.execute_install(
            context.operation_id,
            str(context.payload["plan_id"]),
            str(context.payload.get("correlation_id", "executor")),
        )

    def _execute_uninstall(self, context: ExecutionContext) -> None:
        self.installer.execute_uninstall(
            context.operation_id,
            UninstallRequest.model_validate(context.payload["request"]),
            str(context.payload.get("correlation_id", "executor")),
        )

    def _execute_restore(self, context: ExecutionContext) -> None:
        self.installer.execute_restore(
            context.operation_id,
            RestoreRequest.model_validate(context.payload["request"]),
            str(context.payload.get("correlation_id", "executor")),
        )

    def _execute_configuration(self, context: ExecutionContext) -> dict | None:
        return self.configuration.execute_plan(
            context.operation_id, str(context.payload["plan_id"])
        )

    def _execute_native_configuration(self, context: ExecutionContext) -> dict | None:
        context.safe_checkpoint()
        return self.native_configuration.execute_plan(
            context.operation_id, str(context.payload["plan_id"])
        )

    def _execute_telegram_bot_verify(self, context: ExecutionContext) -> dict:
        context.safe_checkpoint()
        slot = str(context.payload["slot"])
        if slot not in {"hermes", "claude", "codex"}:
            raise OperationExecutionError("TELEGRAM_SLOT_INVALID", "Telegram bot slot is invalid.")
        identity = self.telegram_identities.verify(slot)  # type: ignore[arg-type]
        context.safe_checkpoint()
        return identity.model_dump(mode="json")

    def _execute_telegram_webhook_delete(self, context: ExecutionContext) -> dict:
        context.safe_checkpoint()
        slot = str(context.payload["slot"])
        if slot not in {"hermes", "claude", "codex"}:
            raise OperationExecutionError("TELEGRAM_SLOT_INVALID", "Telegram bot slot is invalid.")
        deleted = self.telegram_identities.delete_webhook(
            slot,  # type: ignore[arg-type]
            explicit_confirmation=bool(context.payload["explicit_confirmation"]),
            drop_pending_updates=bool(context.payload.get("drop_pending_updates", False)),
        )
        return {"slot": slot, "webhook_deleted": deleted}

    def _execute_ownership_handoff(self, context: ExecutionContext) -> dict | None:
        return self.lifecycle.execute_ownership_handoff(
            context.operation_id, str(context.payload["plan_id"])
        )

    def _execute_lifecycle(self, context: ExecutionContext) -> dict | None:
        action = str(context.payload["action"])
        if action not in {"start", "stop", "restart", "reconcile", "health"}:
            raise ValueError("invalid persisted lifecycle action")
        return self.lifecycle.execute_action(
            context.operation_id,
            action,  # type: ignore[arg-type]
            LifecycleActionRequest.model_validate(context.payload["request"]),
        )

    def _installer_recovery_probe(self, operation_id: str, _payload: dict) -> RecoveryDecision:
        with self.db.session() as session:
            operation = OperationStore(session).get(operation_id)
        if operation is None:
            return RecoveryDecision.fail(code="OPERATION_NOT_FOUND")
        safe_phases = {"queued", "dispatching", "recovered_queued"}
        if operation.progress.phase in safe_phases:
            return RecoveryDecision.requeue()
        return RecoveryDecision.fail(
            code="INSTALLER_RECOVERY_REQUIRES_ROLLBACK",
            message="Interrupted installer state requires snapshot recovery before a new attempt.",
            recovery_actions=["inspect_install_snapshot", "create_new_install_plan"],
        )


_STATE: AppState | None = None


def get_state() -> AppState:
    assert _STATE is not None, "AppState 未初始化"
    return _STATE


def init_state(
    settings: Settings,
    adapters: list | None = None,
    installer_fault_injector=None,
    credential_backend: SecretBackend | None = None,
    telegram_client: TelegramBotApiClient | None = None,
    hermes_path_lookup=None,
) -> None:
    global _STATE
    _STATE = AppState(
        settings,
        adapters,
        installer_fault_injector,
        credential_backend,
        telegram_client,
        hermes_path_lookup,
    )


def _bearer_auth(authorization: str | None = Header(default=None)) -> str:
    # 仅接受 Authorization: Bearer <token>;禁止 query token
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHENTICATED", "user_message": "缺少有效 Bearer。"},
        )
    token = authorization.split(" ", 1)[1]
    state = get_state()
    if token != state.settings.bearer_token():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHENTICATED", "user_message": "Bearer 无效。"},
        )
    return token


def _check_loopback(request: Request) -> None:
    # 校验 Host 头为 loopback(防 DNS rebinding);uvicorn 已绑 127.0.0.1 保证物理 loopback。
    host = request.headers.get("host", "").lower()
    ok = (
        host == "127.0.0.1"
        or host.startswith("127.0.0.1:")
        or host == "localhost"
        or host.startswith("localhost:")
        or host == "[::1]"
        or host.startswith("[::1]:")
        or host == "::1"
    )
    if not ok:
        raise HTTPException(
            status_code=403, detail={"code": "NON_LOOPBACK", "user_message": "仅允许 loopback。"}
        )


def _correlation(x_correlation_id: str | None) -> str:
    return x_correlation_id or f"corr-{uuid.uuid4().hex[:12]}"


def _problem_response(err: ControlPlaneError) -> JSONResponse:
    # 响应前再次脱敏(防御性)
    payload = redact_value(err.problem.model_dump(mode="json"))
    return JSONResponse(
        status_code=err.problem.status, content=payload, media_type="application/problem+json"
    )


def create_app(
    settings: Settings | None = None,
    adapters: list | None = None,
    installer_fault_injector=None,
    credential_backend: SecretBackend | None = None,
    telegram_client: TelegramBotApiClient | None = None,
    hermes_path_lookup=None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    init_state(
        settings,
        adapters,
        installer_fault_injector,
        credential_backend,
        telegram_client,
        hermes_path_lookup,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        state = get_state()
        state.start()
        try:
            yield
        finally:
            state.stop()

    app = FastAPI(
        title="AI Agent Desktop Local Control Plane API",
        version=settings.service_version,
        openapi_url="/api/v1/openapi.json",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def loopback_guard(request: Request, call_next):
        _check_loopback(request)
        # 响应体脱敏在路由层处理;此处只做 loopback
        return await call_next(request)

    @app.exception_handler(ControlPlaneError)
    async def _cp_error_handler(_request: Request, exc: ControlPlaneError):
        return _problem_response(exc)

    @app.exception_handler(IdempotencyKeyReuse)
    async def _idem_handler(_request: Request, exc: IdempotencyKeyReuse):
        return JSONResponse(
            status_code=409,
            content=Problem(
                code="IDEMPOTENCY_KEY_REUSE",
                title="Idempotency key reuse",
                status=409,
                detail=f"幂等键 {exc.key} 已用于不同请求体。",
                user_message="幂等键已用于不同请求,请使用新键。",
                retryable=False,
                recovery_actions=["use_new_idempotency_key"],
                correlation_id="default",
            ).model_dump(),
            media_type="application/problem+json",
        )

    @app.exception_handler(InstallerError)
    async def _installer_error_handler(_request: Request, exc: InstallerError):
        status_code = 409
        if exc.code.endswith("NOT_FOUND"):
            status_code = 404
        elif exc.code in {
            "MANIFEST_INVALID",
            "DOWNLOAD_URL_NOT_ALLOWED",
            "ARTIFACT_SOURCE_INCOMPLETE",
            "PATH_IDENTIFIER_INVALID",
        }:
            status_code = 422
        elif exc.code in {
            "ARTIFACT_DOWNLOAD_INTERRUPTED",
            "ARTIFACT_DOWNLOAD_HTTP_FAILED",
            "TRUSTED_ARTIFACT_SOURCE_UNAVAILABLE",
        }:
            status_code = 503
        problem = Problem(
            code=exc.code,
            title=exc.code.replace("_", " ").title(),
            status=status_code,
            detail=exc.message,
            user_message=exc.message,
            retryable=exc.retryable,
            recovery_actions=exc.recovery_actions,
            correlation_id="installer",
        )
        return JSONResponse(
            status_code=status_code,
            content=redact_value(problem.model_dump(mode="json")),
            media_type="application/problem+json",
        )

    @app.exception_handler(OperationExecutionError)
    async def _operation_execution_error_handler(_request: Request, exc: OperationExecutionError):
        error = exc.error
        status_code = 409
        if error.code.endswith("NOT_FOUND"):
            status_code = 404
        elif error.code in {
            "TELEGRAM_TIMEOUT",
            "TELEGRAM_DNS_ERROR",
            "TELEGRAM_TLS_ERROR",
            "TELEGRAM_NETWORK_ERROR",
            "TELEGRAM_RATE_LIMITED",
        }:
            status_code = 503
        elif error.code in {
            "TELEGRAM_SLOT_INVALID",
            "TELEGRAM_UNAUTHORIZED",
            "TELEGRAM_FORBIDDEN",
            "TELEGRAM_IDENTITY_INVALID",
        }:
            status_code = 422
        problem = Problem(
            code=error.code,
            title=error.code.replace("_", " ").title(),
            status=status_code,
            detail=error.message,
            user_message=error.message,
            retryable=error.retryable,
            recovery_actions=error.recovery_actions,
            correlation_id="operation",
        )
        return JSONResponse(
            status_code=status_code,
            content=redact_value(problem.model_dump(mode="json")),
            media_type="application/problem+json",
        )

    @app.exception_handler(CredentialBackendError)
    async def _credential_error_handler(_request: Request, exc: CredentialBackendError):
        status_code = 409
        if exc.status.value == "backend_unavailable":
            status_code = 503
        elif exc.status.value == "inaccessible":
            status_code = 403
        problem = Problem(
            code=exc.code,
            title=exc.code.replace("_", " ").title(),
            status=status_code,
            detail=exc.message,
            user_message=exc.message,
            retryable=exc.status.value in {"unknown", "backend_unavailable"},
            recovery_actions=["inspect_credential_backend", "retry_explicitly"],
            correlation_id="credential",
        )
        return JSONResponse(
            status_code=status_code,
            content=redact_value(problem.model_dump(mode="json")),
            media_type="application/problem+json",
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(_request: Request, exc: RequestValidationError):
        errors = []
        for item in exc.errors():
            errors.append(
                {key: value for key, value in item.items() if key not in {"input", "url", "ctx"}}
            )
        return JSONResponse(
            status_code=422,
            content={
                "code": "REQUEST_VALIDATION_FAILED",
                "title": "Request validation failed",
                "status": 422,
                "detail": "The request did not match the API schema.",
                "user_message": "The request contains invalid or missing fields.",
                "retryable": False,
                "recovery_actions": ["review_request_schema"],
                "correlation_id": "validation",
                "errors": errors,
            },
            media_type="application/problem+json",
        )

    api = app  # 直接在 app 上定义路由(切片最小)

    @api.get("/api/v1/system", response_model=SystemInfo, tags=["System"])
    def get_system(_token: str = Depends(_bearer_auth)):
        st = get_state()
        return SystemInfo(
            instance_id=st.instance_id,
            api_version="v1",
            contract_version=st.settings.contract_version,
            service_version=st.settings.service_version,
            started_at=st.started_at,
            epoch=st.events.epoch,
        )

    @api.get("/api/v1/system/capabilities", response_model=list[Capability], tags=["System"])
    def list_system_capabilities(_token: str = Depends(_bearer_auth)):
        caps: list[Capability] = []
        for a in get_state().registry.all():
            caps.extend(a.capabilities())
        return redact_value(caps)

    @api.post("/api/v1/discovery:run", status_code=202, tags=["Discovery"])
    async def run_discovery(
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
        _token: str = Depends(_bearer_auth),
    ):
        st = get_state()
        corr = _correlation(x_correlation_id)
        body = await request.body()  # 规范化 body 摘要,用于幂等校验
        with st.db.session() as s:
            store = OperationStore(s)
            try:
                op, reused = store.create(
                    kind="discovery",
                    target_ref=ResourceRef(kind="system", id="local"),
                    idempotency_key=idempotency_key,
                    method="POST",
                    resource="/api/v1/discovery:run",
                    body=body,
                )
            except IdempotencyKeyReuse:
                raise
        if not reused:
            st.executor.submit(
                operation_id=op.operation_id,
                component_id="system",
                kind="discovery",
                payload={"correlation_id": corr},
            )
        response.headers["Location"] = f"/api/v1/operations/{op.operation_id}"
        response.headers["X-Correlation-ID"] = corr
        return redact_value(op.model_dump(mode="json"))

    @api.get("/api/v1/readiness", response_model=ReadinessReport, tags=["Discovery"])
    def get_readiness(
        x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
        _token: str = Depends(_bearer_auth),
    ):
        st = get_state()
        with st.db.session() as s:
            store = OperationStore(s)
            ops = store.list_operations(kind="discovery", limit=20)
        for op in ops:
            if op.status == OperationStatus.SUCCEEDED and op.result:
                report = ReadinessReport.model_validate(op.result)
                return redact_value(report)
        raise ControlPlaneError(
            code="READINESS_NOT_AVAILABLE",
            title="No readiness report",
            status=404,
            detail="尚无已完成的就绪扫描。",
            user_message="尚未执行就绪扫描,请先调用 discovery:run。",
            retryable=True,
            recovery_actions=["run_discovery"],
            correlation_id=_correlation(x_correlation_id),
        )

    @api.get("/api/v1/components", response_model=list[Component], tags=["Components"])
    def list_components(_token: str = Depends(_bearer_auth)):
        st = get_state()
        with st.db.session() as s:
            store = OperationStore(s)
            ops = store.list_operations(kind="discovery", limit=20)
        for op in ops:
            if op.status == OperationStatus.SUCCEEDED and op.result:
                report = ReadinessReport.model_validate(op.result)
                return redact_value(report.components)
        return []

    @api.get("/api/v1/components/{component_id}", response_model=Component, tags=["Components"])
    def get_component(component_id: str, _token: str = Depends(_bearer_auth)):
        st = get_state()
        with st.db.session() as s:
            store = OperationStore(s)
            ops = store.list_operations(kind="discovery", limit=20)
        for op in ops:
            if op.status == OperationStatus.SUCCEEDED and op.result:
                report = ReadinessReport.model_validate(op.result)
                for c in report.components:
                    if c.component_id == component_id:
                        return redact_value(c)
        raise ControlPlaneError(
            code="COMPONENT_NOT_FOUND",
            title="Component not found",
            status=404,
            detail=f"组件 {component_id} 未找到或尚未发现。",
            user_message="未找到该组件,请先执行发现。",
            retryable=True,
            recovery_actions=["run_discovery"],
        )

    @api.get("/api/v1/operations", response_model=list[Operation], tags=["Operations"])
    def list_operations(
        op_status: str | None = None,
        kind: str | None = None,
        target_id: str | None = None,
        _token: str = Depends(_bearer_auth),
    ):
        st = get_state()
        with st.db.session() as s:
            store = OperationStore(s)
            ops = store.list_operations(status=op_status, kind=kind, target_id=target_id, limit=50)
        return redact_value([o.model_dump(mode="json") for o in ops])

    @api.get("/api/v1/operations/{operation_id}", response_model=Operation, tags=["Operations"])
    def get_operation(operation_id: str, _token: str = Depends(_bearer_auth)):
        st = get_state()
        with st.db.session() as s:
            store = OperationStore(s)
            op = store.get(operation_id)
        if op is None:
            raise ControlPlaneError(
                code="OPERATION_NOT_FOUND",
                title="Operation not found",
                status=404,
                detail=f"Operation {operation_id} 不存在。",
                user_message="未找到该操作。",
                retryable=False,
                recovery_actions=[],
            )
        return redact_value(op.model_dump(mode="json"))

    @api.get(
        "/api/v1/operations/{operation_id}/events",
        response_model=list[OperationAuditEvent],
        tags=["Operations"],
    )
    def get_operation_events(operation_id: str, _token: str = Depends(_bearer_auth)):
        st = get_state()
        with st.db.session() as s:
            if OperationStore(s).get(operation_id) is None:
                raise ControlPlaneError(
                    code="OPERATION_NOT_FOUND",
                    title="Operation not found",
                    status=404,
                    detail="Operation does not exist.",
                    user_message="未找到该操作。",
                    retryable=False,
                )
        return redact_value(
            [item.model_dump(mode="json") for item in st.installer.list_audit_events(operation_id)]
        )

    @api.post("/api/v1/operations/{operation_id}:cancel", status_code=202, tags=["Operations"])
    async def cancel_operation(
        operation_id: str,
        payload: CancelRequest,
        request: Request,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        _token: str = Depends(_bearer_auth),
    ):
        st = get_state()
        raw_body = await request.body()
        newly_recorded = False
        with st.db.session() as s:
            store = OperationStore(s)
            op = store.get(operation_id)
            if op is None:
                raise ControlPlaneError(
                    code="OPERATION_NOT_FOUND",
                    title="Operation not found",
                    status=404,
                    detail=f"Operation {operation_id} 不存在。",
                    user_message="未找到该操作。",
                    retryable=False,
                )
            resource = f"/api/v1/operations/{operation_id}:cancel"
            existing = s.get(IdempotencyRecord, idempotency_key)
            digest = body_digest(raw_body)
            if existing is not None:
                if (
                    existing.method != "POST"
                    or existing.resource != resource
                    or existing.body_digest != digest
                    or existing.operation_id != operation_id
                ):
                    raise IdempotencyKeyReuse(idempotency_key)
                return redact_value(op.model_dump(mode="json"))
            if op.status in (
                OperationStatus.SUCCEEDED,
                OperationStatus.FAILED,
                OperationStatus.CANCELED,
            ):
                raise ControlPlaneError(
                    code="OPERATION_ALREADY_TERMINATED",
                    title="Operation already terminated",
                    status=409,
                    detail="终态操作不可取消。",
                    user_message="该操作已结束,无法取消。",
                    retryable=False,
                )
            s.add(
                IdempotencyRecord(
                    idempotency_key=idempotency_key,
                    method="POST",
                    resource=resource,
                    body_digest=digest,
                    operation_id=operation_id,
                    response_status=202,
                    created_at=datetime.now(UTC),
                )
            )
            newly_recorded = True
            store.transition(
                operation_id,
                status=OperationStatus.CANCEL_REQUESTED,
                phase="cancel_requested",
                message="Cancellation requested; completion waits for a safe checkpoint.",
            )
            op = store.get(operation_id)
        assert op is not None
        if newly_recorded and op.kind in {
            "cc_connect_install",
            "cc_connect_uninstall",
            "cc_connect_restore",
        }:
            st.installer.audit_cancel_requested(
                operation_id, point_of_no_return=op.progress.point_of_no_return
            )
        return redact_value(op.model_dump(mode="json"))

    @api.post(
        "/api/v1/components/{component_id}/install-plan",
        response_model=InstallPlan,
        status_code=201,
        tags=["Components"],
    )
    def create_install_plan(
        component_id: str,
        payload: InstallPlanRequest,
        _token: str = Depends(_bearer_auth),
    ):
        if component_id != "cc-connect":
            raise capability_unsupported(component_id, "install")
        return redact_value(get_state().installer.create_plan(payload).model_dump(mode="json"))

    @api.get(
        "/api/v1/components/{component_id}/install-plans/{plan_id}",
        response_model=InstallPlan,
        tags=["Components"],
    )
    def get_install_plan(component_id: str, plan_id: str, _token: str = Depends(_bearer_auth)):
        if component_id != "cc-connect":
            raise capability_unsupported(component_id, "install")
        plan = get_state().installer.get_plan(plan_id)
        if plan is None:
            raise InstallerError(
                "INSTALL_PLAN_NOT_FOUND",
                "Install plan was not found.",
                recovery_actions=["create_install_plan"],
            )
        return redact_value(plan.model_dump(mode="json"))

    @api.post("/api/v1/components/{component_id}:install", status_code=202, tags=["Components"])
    async def install_component(
        component_id: str,
        request: Request,
        response: Response,
        payload: InstallConfirmationRequest | None = None,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
        _token: str = Depends(_bearer_auth),
    ):
        if component_id != "cc-connect":
            raise capability_unsupported(component_id, "install")
        if payload is None:
            raise InstallerError(
                "INSTALL_CONFIRMATION_REQUIRED",
                "A persisted install plan and explicit confirmation are required.",
                recovery_actions=["create_install_plan", "confirm_install_plan"],
            )
        st = get_state()
        raw_body = await request.body()
        operation, reused = st.installer.confirm_install(
            payload, idempotency_key=idempotency_key, body=raw_body
        )
        correlation_id = _correlation(x_correlation_id)
        if not reused:
            st.executor.submit(
                operation_id=operation.operation_id,
                component_id=component_id,
                kind="cc_connect_install",
                payload={"plan_id": payload.plan_id, "correlation_id": correlation_id},
            )
        response.headers["Location"] = f"/api/v1/operations/{operation.operation_id}"
        response.headers["X-Correlation-ID"] = correlation_id
        return redact_value(operation.model_dump(mode="json"))

    @api.post("/api/v1/components/{component_id}:uninstall", status_code=202, tags=["Components"])
    async def uninstall_component(
        component_id: str,
        payload: UninstallRequest,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
        _token: str = Depends(_bearer_auth),
    ):
        if component_id != "cc-connect":
            raise capability_unsupported(component_id, "uninstall")
        st = get_state()
        operation, reused = st.installer.create_uninstall_operation(
            payload, idempotency_key=idempotency_key, body=await request.body()
        )
        correlation_id = _correlation(x_correlation_id)
        if not reused:
            st.executor.submit(
                operation_id=operation.operation_id,
                component_id=component_id,
                kind="cc_connect_uninstall",
                payload={
                    "request": payload.model_dump(mode="json"),
                    "correlation_id": correlation_id,
                },
            )
        response.headers["Location"] = f"/api/v1/operations/{operation.operation_id}"
        return redact_value(operation.model_dump(mode="json"))

    @api.post("/api/v1/components/{component_id}:restore", status_code=202, tags=["Components"])
    async def restore_component(
        component_id: str,
        payload: RestoreRequest,
        request: Request,
        response: Response,
        idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16, max_length=256),
        x_correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
        _token: str = Depends(_bearer_auth),
    ):
        if component_id != "cc-connect":
            raise capability_unsupported(component_id, "restore")
        st = get_state()
        operation, reused = st.installer.create_restore_operation(
            payload, idempotency_key=idempotency_key, body=await request.body()
        )
        correlation_id = _correlation(x_correlation_id)
        if not reused:
            st.executor.submit(
                operation_id=operation.operation_id,
                component_id=component_id,
                kind="cc_connect_restore",
                payload={
                    "request": payload.model_dump(mode="json"),
                    "correlation_id": correlation_id,
                },
            )
        response.headers["Location"] = f"/api/v1/operations/{operation.operation_id}"
        return redact_value(operation.model_dump(mode="json"))

    @api.get(
        "/api/v1/components/{component_id}/managed-versions",
        response_model=list[ManagedVersion],
        tags=["Components"],
    )
    def list_managed_versions(component_id: str, _token: str = Depends(_bearer_auth)):
        if component_id != "cc-connect":
            raise capability_unsupported(component_id, "managed-versions")
        return redact_value(
            [item.model_dump(mode="json") for item in get_state().installer.list_managed_versions()]
        )

    @api.get("/api/v1/diagnostics", response_model=list[Diagnostic], tags=["Diagnostics"])
    def list_diagnostics(_token: str = Depends(_bearer_auth)):
        st = get_state()
        persisted: list[Diagnostic] = []
        with st.db.session() as s:
            records = list(
                s.scalars(
                    select(DiagnosticRecord).order_by(DiagnosticRecord.created_at.desc()).limit(50)
                )
            )
            persisted = [_diagnostic_from_record(record) for record in records]
            store = OperationStore(s)
            ops = store.list_operations(kind="discovery", limit=20)
        for op in ops:
            if op.status == OperationStatus.SUCCEEDED and op.result:
                report = ReadinessReport.model_validate(op.result)
                return redact_value([*persisted, *report.blockers, *report.warnings])
        return redact_value(persisted)

    def _diagnostic_from_record(record: DiagnosticRecord) -> Diagnostic:
        return Diagnostic(
            diagnostic_id=record.diagnostic_id,
            severity=DiagnosticSeverity(record.severity),
            code=record.code,
            summary=record.summary,
            user_message=record.user_message,
            suggested_actions=json.loads(record.suggested_actions_json),
            technical_details=json.loads(record.technical_details_json),
            redaction_applied=True,
            created_at=record.created_at,
            correlation_id=record.correlation_id,
            operation_id=record.operation_id,
            target_ref=(
                ResourceRef(kind=record.target_kind, id=record.target_id)
                if record.target_kind and record.target_id
                else None
            ),
        )

    @api.get("/api/v1/diagnostics/{diagnostic_id}", response_model=Diagnostic, tags=["Diagnostics"])
    def get_diagnostic(diagnostic_id: str, _token: str = Depends(_bearer_auth)):
        with get_state().db.session() as session:
            record = session.get(DiagnosticRecord, diagnostic_id)
            if record is None:
                raise ControlPlaneError(
                    code="DIAGNOSTIC_NOT_FOUND",
                    title="Diagnostic not found",
                    status=404,
                    detail="Diagnostic does not exist.",
                    user_message="未找到该诊断。",
                    retryable=False,
                )
            return redact_value(_diagnostic_from_record(record).model_dump(mode="json"))

    @api.get("/api/v1/events", tags=["Events"])
    async def subscribe_events(
        request: Request,
        topics: str | None = None,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        _token: str = Depends(_bearer_auth),
    ):
        st = get_state()
        try:
            queue, replay = st.events.subscribe(last_event_id)
        except CursorExpired:
            return JSONResponse(
                status_code=410,
                content=Problem(
                    code="EVENT_CURSOR_EXPIRED",
                    title="Event cursor expired",
                    status=410,
                    detail="游标已过期,请先取新快照再重新订阅。",
                    user_message="事件游标已过期,请重新获取状态后再订阅。",
                    retryable=True,
                    recovery_actions=["fetch_snapshot", "resubscribe"],
                    correlation_id="default",
                ).model_dump(),
                media_type="application/problem+json",
            )

        topic_set = set(topics.split(",")) if topics else None

        async def event_gen():
            # 首块:连接确认,让客户端立即收到响应
            yield ": connected\n\n"
            try:
                for ev in replay:
                    if topic_set and not any(ev.type.startswith(t) for t in topic_set):
                        continue
                    yield ev.to_sse()
                while True:
                    try:
                        ev = await asyncio.wait_for(queue.get(), timeout=30.0)
                    except TimeoutError:
                        # 心跳,保持连接
                        yield ": ping\n\n"
                        continue
                    if topic_set and not any(ev.type.startswith(t) for t in topic_set):
                        continue
                    yield ev.to_sse()
            finally:
                st.events.unsubscribe(queue)

        return StreamingResponse(event_gen(), media_type="text/event-stream")

    app.include_router(build_configuration_router(get_state, _bearer_auth))
    app.include_router(build_lifecycle_router(get_state, _bearer_auth))
    app.include_router(build_integrations_router(get_state, _bearer_auth))
    app.include_router(build_credentials_router(get_state, _bearer_auth))
    app.include_router(build_telegram_router(get_state, _bearer_auth))
    app.include_router(build_native_configuration_router(get_state, _bearer_auth))
    app.include_router(build_observability_router(get_state, _bearer_auth))

    return app

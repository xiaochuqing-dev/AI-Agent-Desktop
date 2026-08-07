from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sys
import threading
import tkinter as tk
import uuid
from datetime import UTC, datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from ..credentials.models import PUBLIC_CREDENTIAL_REFERENCES
from ..credentials.service import CredentialService
from ..credentials.windows_backend import CredentialBackendError
from ..infrastructure.config import Settings
from ..observability.models import (
    E2ETestConfirmation,
    E2ETestResponseEvidence,
    LinkId,
)
from ..observability.service import LiveE2ETestService
from ..operations import ExecutionContext, OperationExecutionError
from ..persistence.session import Database
from ..security.redaction import redact_value
from ..telegram.api_client import TelegramBotApiClient
from ..telegram.binding_service import SLOTS, TelegramBindingService
from ..telegram.bot_identity import TelegramBotIdentityService
from ..telegram.models import BindingSession, BindingSessionCreated
from ..telegram.update_lease import TelegramUpdateLeaseService

CANDIDATE_VERSION = "0.1.0-stage-a"
STEPS = (
    "system",
    "components",
    "credentials",
    "bot_identity",
    "private_binding",
    "group_binding",
    "six_links",
    "report",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _probe_command(names: tuple[str, ...], candidate_root: Path) -> dict[str, Any]:
    candidates = [candidate_root / name for name in names]
    for name in names:
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return {"status": "observed", "path": str(candidate.resolve())}
    return {"status": "unknown", "path": None}


def run_headless_checks(candidate_root: Path | None = None) -> dict[str, Any]:
    root = (candidate_root or Path.cwd()).resolve()
    system = {
        "platform": platform.system(),
        "release": platform.release(),
        "architecture": platform.machine(),
        "python_embedded": bool(getattr(sys, "_MEIPASS", None)),
        "path": str(root),
        "ordinary_user": (os.name == "nt" or os.geteuid() != 0 if hasattr(os, "geteuid") else True),
    }
    components = {
        "hermes": _probe_command(("hermes", "hermes.exe"), root),
        "claude": _probe_command(("claude", "claude.exe"), root),
        "codex": _probe_command(("codex", "codex.exe"), root),
        "cc_connect": _probe_command(
            (str(root / "cc-connect" / "cc-connect.exe"), "cc-connect", "cc-connect.exe"),
            root,
        ),
        "chrome_agent": False,
    }
    return {
        "candidate_version": CANDIDATE_VERSION,
        "status": "candidate_ready",
        "generated_at": datetime.now(UTC).isoformat(),
        "steps": {step: "pending_user_validation" for step in STEPS},
        "system": system,
        "components": components,
        "bot_identities": [],
        "binding": {"state": "not_started", "bound_private_count": 0, "bound_group_count": 0},
        "links": [],
        "e2e_runs": [],
        "telegram_messages_sent": 0,
        "reference_baseline_modified": False,
        "external_environment_modified": False,
        "secret_values_recorded": 0,
        "message_bodies_recorded": 0,
    }


def export_redacted_report(report: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    safe = redact_value(report)
    safe["exported_at"] = datetime.now(UTC).isoformat()
    safe["redaction_applied"] = True
    output_path.write_text(json.dumps(safe, ensure_ascii=True, indent=2), encoding="utf-8")
    return output_path


def cleanup_validation_data(candidate_root: Path) -> list[str]:
    """Remove only candidate-owned temporary state and reports.

    Credential Manager entries are intentionally outside this cleanup boundary.
    """

    root = candidate_root.resolve()
    targets = (root / "reports" / "user-validation-redacted.json", root / "validation-data")
    removed: list[str] = []
    for target in targets:
        resolved = target.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError:
            raise ValueError("cleanup target escaped candidate root") from None
        if resolved.is_file():
            resolved.unlink()
            removed.append(str(resolved))
        elif resolved.is_dir():
            shutil.rmtree(resolved)
            removed.append(str(resolved))
    return removed


class _ValidationRuntime:
    """Small in-process facade used by the acceptance wizard only."""

    def __init__(self, candidate_root: Path) -> None:
        data_dir = candidate_root / "validation-data"
        settings = Settings(data_dir=str(data_dir))
        self.database = Database(settings)
        self.credentials = CredentialService(self.database)
        self.telegram_client = TelegramBotApiClient()
        self.identities = TelegramBotIdentityService(
            self.database, self.credentials, self.telegram_client
        )
        self.leases = TelegramUpdateLeaseService(self.database)
        self.binding = TelegramBindingService(
            self.database,
            self.credentials,
            self.identities,
            self.leases,
            self.telegram_client,
        )
        self.observability = LiveE2ETestService(
            self.database,
            credentials=self.credentials,
            identities=self.identities,
            binding=self.binding,
            telegram_client=self.telegram_client,
        )

    def close(self) -> None:
        self.database.engine.dispose()


class ValidationWizard:
    """Acceptance-only window with explicit user-controlled network actions."""

    def __init__(self, *, candidate_root: Path | None = None) -> None:
        self.candidate_root = (candidate_root or Path.cwd()).resolve()
        self.report = run_headless_checks(self.candidate_root)
        self._runtime: _ValidationRuntime | None = None
        self._binding: BindingSession | BindingSessionCreated | None = None
        self._plans: dict[str, Any] = {}
        self._runs: dict[str, Any] = {}
        self._polling = False
        self.root = tk.Tk()
        self.root.title("AI-Agent-Desktop 验收向导")
        self.root.geometry("1040x820")
        self.root.minsize(860, 680)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._build()

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text="AI-Agent-Desktop 用户验收向导",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text="阶段 A 候选包。启动和刷新不会发送 Telegram；每次真实测试都需要单独确认。",
            wraplength=980,
        ).pack(anchor="w", pady=(4, 10))
        self.status = tk.StringVar(value="系统检查完成，等待用户验证。")
        ttk.Label(outer, textvariable=self.status).pack(anchor="w", pady=(0, 8))

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True)
        self._build_overview_tab()
        self._build_credentials_tab()
        self._build_binding_tab()
        self._build_links_tab()

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(10, 0))
        ttk.Button(controls, text="刷新检查", command=self.refresh).pack(side="left")
        ttk.Button(controls, text="导出脱敏报告", command=self.export).pack(side="left", padx=8)
        ttk.Button(controls, text="清理验收数据", command=self.cleanup).pack(side="left")
        ttk.Button(controls, text="关闭", command=self.close).pack(side="right")

    def _build_overview_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="总览")
        self.tree = ttk.Treeview(tab, columns=("step", "status"), show="headings", height=10)
        self.tree.heading("step", text="步骤")
        self.tree.heading("status", text="状态")
        self.tree.column("step", width=360, anchor="w")
        self.tree.column("status", width=360, anchor="w")
        self.tree.pack(fill="x", expand=False)
        for step, status in self.report["steps"].items():
            self.tree.insert("", "end", iid=step, values=(step, status))
        self.log = tk.Text(tab, height=18, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, pady=(12, 0))

    def _build_credentials_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="三个 Bot")
        ttk.Label(
            tab, text="Token 只写入当前用户的 Credential Manager；向导不保存或导出 Token。"
        ).pack(anchor="w")
        self.token_vars: dict[str, tk.StringVar] = {}
        self.identity_labels: dict[str, tk.StringVar] = {}
        for slot in SLOTS:
            row = ttk.Frame(tab)
            row.pack(fill="x", pady=(10, 0))
            ttk.Label(row, text=f"{slot.title()} Bot Token", width=20).pack(side="left")
            variable = tk.StringVar()
            self.token_vars[slot] = variable
            entry = ttk.Entry(row, textvariable=variable, show="*", width=62)
            entry.pack(side="left", fill="x", expand=True)
            label = tk.StringVar(value="尚未验证")
            self.identity_labels[slot] = label
            ttk.Label(row, textvariable=label, width=30).pack(side="left", padx=(8, 0))
        ttk.Button(tab, text="验证三个 Bot（各一次 getMe）", command=self.verify_bots).pack(
            anchor="w", pady=(14, 0)
        )
        ttk.Label(
            tab,
            text="验证失败不会自动重试；修正 Token 后再次明确点击验证。三个 Bot ID 必须唯一。",
            wraplength=920,
        ).pack(anchor="w", pady=(8, 0))

    def _build_binding_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="绑定")
        self.binding_status = tk.StringVar(value="尚未创建绑定会话")
        ttk.Label(tab, textvariable=self.binding_status).pack(anchor="w")
        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="创建绑定会话", command=self.create_binding).pack(side="left")
        ttk.Button(buttons, text="检查三 Bot 更新", command=self.poll_binding).pack(
            side="left", padx=8
        )
        ttk.Button(buttons, text="取消绑定会话", command=self.cancel_binding).pack(side="left")
        self.binding_text = tk.Text(tab, height=18, wrap="word", state="disabled")
        self.binding_text.pack(fill="both", expand=True, pady=(12, 0))

    def _build_links_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="六条链路")
        self.links_tree = ttk.Treeview(
            tab,
            columns=("link", "status", "evidence", "diagnostic"),
            show="headings",
            height=12,
        )
        for column, title, width in (
            ("link", "链路", 170),
            ("status", "状态", 190),
            ("evidence", "证据", 130),
            ("diagnostic", "诊断", 360),
        ):
            self.links_tree.heading(column, text=title)
            self.links_tree.column(column, width=width, anchor="w")
        self.links_tree.pack(fill="both", expand=True)
        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="刷新六链路", command=self.refresh_links).pack(side="left")
        ttk.Button(buttons, text="创建一次性计划", command=self.create_plan).pack(
            side="left", padx=8
        )
        ttk.Button(buttons, text="确认并发送一条", command=self.confirm_plan).pack(side="left")
        ttk.Button(buttons, text="取消计划", command=self.cancel_plan).pack(side="left", padx=8)
        ttk.Button(buttons, text="录入响应证据", command=self.record_response).pack(side="left")
        ttk.Button(buttons, text="运行六条合成验收", command=self.run_synthetic).pack(side="right")

    def _runtime_or_error(self) -> _ValidationRuntime | None:
        if self._runtime is not None:
            return self._runtime
        try:
            self._runtime = _ValidationRuntime(self.candidate_root)
            return self._runtime
        except Exception as exc:
            self._show_error("初始化本地验收状态失败", exc)
            return None

    def verify_bots(self) -> None:
        runtime = self._runtime_or_error()
        if runtime is None:
            return
        tokens = {slot: variable.get().strip() for slot, variable in self.token_vars.items()}
        if any(not token for token in tokens.values()):
            messagebox.showwarning("需要 Token", "请填写三个 Bot Token 后再验证。")
            return
        if len(set(tokens.values())) != len(tokens):
            messagebox.showwarning("Bot 冲突", "三个 Token 必须来自三个不同的 Bot。")
            return
        identities = []
        try:
            for slot in SLOTS:
                reference_id = PUBLIC_CREDENTIAL_REFERENCES[slot][0]
                metadata = runtime.credentials.get(reference_id)
                if metadata.status.value == "available":
                    runtime.credentials.replace(
                        reference_id, tokens[slot], operation_id=f"wizard-token-{uuid.uuid4().hex}"
                    )
                else:
                    runtime.credentials.put(
                        reference_id, tokens[slot], operation_id=f"wizard-token-{uuid.uuid4().hex}"
                    )
                identities.append(runtime.identities.verify(slot))
            bot_ids = [item.bot_id for item in identities]
            if len(set(bot_ids)) != len(bot_ids):
                raise OperationExecutionError(
                    "TELEGRAM_BOT_IDENTITY_CONFLICT",
                    "Telegram returned duplicate Bot IDs; use three independent bots.",
                )
            self.report["bot_identities"] = [
                {
                    "slot": item.slot,
                    "bot_id": item.bot_id,
                    "username": item.username,
                    "verification_status": item.verification_status,
                    "credential_revision": item.credential_revision,
                }
                for item in identities
            ]
            self.report["steps"]["credentials"] = "observed"
            self.report["steps"]["bot_identity"] = "observed"
            for item in identities:
                self.identity_labels[item.slot].set(f"@{item.username}  id={item.bot_id}")
            self._write_log("三个 Bot 已分别完成一次 getMe；Token 已从输入框清除。")
            self.status.set("Bot 身份已验证，可创建绑定会话。")
        except (CredentialBackendError, OperationExecutionError, ValueError) as exc:
            self._show_error("Bot 验证未完成", exc)
        finally:
            for variable in self.token_vars.values():
                variable.set("")
            self._refresh_steps()

    def create_binding(self) -> None:
        runtime = self._runtime_or_error()
        if runtime is None:
            return
        try:
            if self._binding is not None and self._binding.state.value not in {
                "canceled",
                "expired",
                "completed",
            }:
                self._write_log("已有活动绑定会话；不会创建第二个会话。")
                return
            created = runtime.binding.create(expires_in_seconds=1800)
            self._binding = created
            self.binding_status.set(
                f"会话 {created.session_id}，状态 {created.state.value}，等待私聊绑定"
            )
            lines = ["私聊：分别打开三个 Bot，并各发送对应命令："]
            for slot in SLOTS:
                lines.append(
                    f"{slot}: {created.private_deep_links[slot]}  {created.private_commands[slot]}"
                )
            lines.append("")
            lines.append("群聊：将三个 Bot 加入同一测试群后，分别发送对应命令：")
            for slot in SLOTS:
                lines.append(f"{slot}: {created.group_commands[slot]}")
            self._set_text(self.binding_text, "\n".join(lines))
            self.report["binding"] = {
                "state": created.state.value,
                "bound_private_count": 0,
                "bound_group_count": 0,
            }
            self._write_log("绑定会话已创建。向导未轮询 Telegram；请点击检查更新。")
            self._refresh_steps()
        except (OperationExecutionError, CredentialBackendError, ValueError) as exc:
            self._show_error("无法创建绑定会话", exc)

    def poll_binding(self) -> None:
        runtime = self._runtime_or_error()
        if runtime is None or self._binding is None:
            messagebox.showwarning("尚未绑定", "请先验证三个 Bot 并创建绑定会话。")
            return
        if self._polling:
            return
        if not messagebox.askyesno(
            "确认检查 Telegram 更新",
            "这会按 Bot 逐个读取绑定所需的更新并短暂持有 Update Lease，是否继续？",
        ):
            return
        self._polling = True
        try:
            for slot in SLOTS:
                context = ExecutionContext(
                    operation_id=f"wizard-binding-{self._binding.session_id}-{slot}-{uuid.uuid4().hex[:8]}",
                    component_id=f"telegram:{slot}",
                    kind="telegram_binding_poll",
                    payload={
                        "session_id": self._binding.session_id,
                        "slot": slot,
                        "timeout_seconds": 0,
                    },
                    database=runtime.database,
                    shutdown_event=threading.Event(),
                )
                try:
                    runtime.binding.poll(context)
                except OperationExecutionError as exc:
                    self._write_log(f"{slot} 绑定检查失败：{exc.error.code}；未自动重试。")
            self._binding = runtime.binding.get(self._binding.session_id)
            self.binding_status.set(
                f"状态 {self._binding.state.value}，私聊 {self._binding.bound_private_count}/3，群聊 {self._binding.bound_group_count}/3"
            )
            self.report["binding"] = {
                "state": self._binding.state.value,
                "bound_private_count": self._binding.bound_private_count,
                "bound_group_count": self._binding.bound_group_count,
            }
            self.report["steps"]["private_binding"] = (
                "observed" if self._binding.bound_private_count == 3 else "pending_user_validation"
            )
            self.report["steps"]["group_binding"] = (
                "observed" if self._binding.bound_group_count == 3 else "pending_user_validation"
            )
            if self._binding.state.value == "completed":
                self._write_log("三个私聊和三个群聊均已绑定，且 User/Group 一致性由服务校验。")
                self.refresh_links()
            else:
                self._write_log("绑定状态已刷新；仍需用户完成待处理命令。")
        finally:
            self._polling = False
            self._refresh_steps()

    def cancel_binding(self) -> None:
        runtime = self._runtime_or_error()
        if runtime is None or self._binding is None:
            return
        if not messagebox.askyesno("确认取消绑定", "取消后不会重发或继续轮询，是否取消？"):
            return
        try:
            self._binding = runtime.binding.cancel(self._binding.session_id, "user_canceled")
            self.binding_status.set("绑定会话已取消；可重新创建显式会话。")
            self.report["binding"]["state"] = self._binding.state.value
            self._write_log("绑定会话已取消。")
            self._refresh_steps()
        except OperationExecutionError as exc:
            self._show_error("取消绑定失败", exc)

    def refresh_links(self) -> None:
        runtime = self._runtime_or_error()
        if runtime is None:
            return
        try:
            links = runtime.observability.list_links()
        except Exception as exc:
            self._show_error("读取六链路失败", exc)
            return
        for item in self.links_tree.get_children():
            self.links_tree.delete(item)
        for state in links:
            self.links_tree.insert(
                "",
                "end",
                iid=state.link_id.value,
                values=(
                    state.link_id.value,
                    state.status.value,
                    state.evidence_level.value,
                    state.diagnostic_code or "",
                ),
            )
        self.report["links"] = [redact_value(item.model_dump(mode="json")) for item in links]
        self.report["steps"]["six_links"] = "observed"
        self._refresh_steps()

    def _selected_link(self) -> LinkId | None:
        selected = self.links_tree.selection()
        if not selected:
            messagebox.showwarning("请选择链路", "请先在六链路列表中选择一条链路。")
            return None
        try:
            return LinkId(selected[0])
        except ValueError:
            return None

    def create_plan(self) -> None:
        link_id = self._selected_link()
        runtime = self._runtime_or_error()
        if link_id is None or runtime is None:
            return
        try:
            plan = runtime.observability.create_plan(link_id)
            self._plans[link_id.value] = plan
            self._write_log(
                f"{link_id.value} 计划已创建：{plan.plan_id}，digest={plan.plan_digest}；尚未发送消息。"
            )
            self.status.set(f"{link_id.value} 已有待确认计划；确认后最多发送一条消息。")
        except Exception as exc:
            self._show_error("无法创建 E2E 计划", exc)

    def confirm_plan(self) -> None:
        link_id = self._selected_link()
        runtime = self._runtime_or_error()
        if link_id is None or runtime is None:
            return
        plan = self._plans.get(link_id.value)
        if plan is None:
            messagebox.showwarning("尚无计划", "请先创建该链路的显式计划。")
            return
        if not messagebox.askyesno(
            "确认发送一条验收消息",
            f"将只向 {link_id.value} 的已绑定聊天发送一条短、只读验收消息。失败或超时不会自动重试。继续？",
        ):
            return
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
        try:
            run = runtime.observability.confirm_plan(
                confirmation, idempotency_key=f"wizard-{uuid.uuid4().hex}"
            )
            self._runs[run.run_id] = run
            self.report["e2e_runs"].append(redact_value(run.model_dump(mode="json")))
            if run.request_message_id is not None:
                self.report["telegram_messages_sent"] += 1
            self._write_log(
                f"{link_id.value} 结果：{run.lifecycle.value}/{run.evidence_level.value}；"
                f"request_message_id={run.request_message_id or 'unknown'}；{run.diagnostic_code or '等待响应证据'}"
            )
            self.refresh_links()
        except Exception as exc:
            self._show_error("一次性 E2E 未完成", exc)

    def cancel_plan(self) -> None:
        link_id = self._selected_link()
        runtime = self._runtime_or_error()
        if link_id is None or runtime is None:
            return
        plan = self._plans.get(link_id.value)
        if plan is None:
            messagebox.showwarning("尚无计划", "请先创建该链路的显式计划。")
            return
        if not messagebox.askyesno("确认取消计划", "取消后不会发送消息，是否继续？"):
            return
        try:
            runtime.observability.cancel_plan(plan.plan_id, confirmation=True)
            self._write_log(f"{link_id.value} 计划已取消；如需重试必须新建计划。")
            self._plans.pop(link_id.value, None)
            self.refresh_links()
        except Exception as exc:
            self._show_error("取消 E2E 计划失败", exc)

    def record_response(self) -> None:
        link_id = self._selected_link()
        runtime = self._runtime_or_error()
        if link_id is None or runtime is None:
            return
        candidates = [run for run in self._runs.values() if run.link_id == link_id]
        if not candidates:
            messagebox.showwarning("尚无运行记录", "请先确认并发送该链路的一次性计划。")
            return
        run = sorted(candidates, key=lambda item: item.created_at)[-1]
        if run.request_message_id is None:
            messagebox.showwarning(
                "缺少请求标识", "本次发送没有可靠的 request message_id，不能录入响应证据。"
            )
            return
        response_id = simpledialog.askinteger(
            "响应 message_id",
            "请输入运行时提供的响应 message_id；向导不会读取 Telegram 或保存正文：",
            parent=self.root,
            minvalue=1,
        )
        if response_id is None:
            return
        state = runtime.observability.get_link(link_id)
        if state.bot_id is None:
            return
        try:
            updated = runtime.observability.record_response(
                E2ETestResponseEvidence(
                    run_id=run.run_id,
                    bot_id=state.bot_id,
                    chat_identity_hash=(
                        state.group_identity_hash
                        if link_id.session_scope == "group"
                        else state.operator_identity_hash
                    )
                    or "",
                    response_message_id=response_id,
                    reply_to_message_id=run.request_message_id,
                )
            )
            self._runs[updated.run_id] = updated
            self.report["e2e_runs"].append(redact_value(updated.model_dump(mode="json")))
            self._write_log(
                f"{link_id.value} 响应证据：{updated.lifecycle.value}/{updated.evidence_level.value}；"
                f"{updated.diagnostic_code or '匹配成功'}"
            )
            self.refresh_links()
        except Exception as exc:
            self._show_error("响应证据未被接受", exc)

    def run_synthetic(self) -> None:
        runtime = self._runtime_or_error()
        if runtime is None:
            return
        try:
            runs = runtime.observability.run_synthetic()
            self._write_log("六条合成 E2E 已完成；证据等级保持 synthetic，未访问 Telegram。")
            self.status.set("六条合成验收通过；真实链路仍需逐条用户确认。")
            self.refresh_links()
            self.report["steps"]["six_links"] = "synthetic_verified"
            self._refresh_steps()
            del runs
        except Exception as exc:
            self._show_error("合成验收失败", exc)

    def refresh(self) -> None:
        fresh = run_headless_checks(self.candidate_root)
        for key in ("candidate_version", "status", "generated_at", "system", "components"):
            self.report[key] = fresh[key]
        if self._runtime is not None:
            self.refresh_links()
        self._refresh_steps()
        self.status.set("检查已刷新；真实绑定和六条链路仍需用户逐条确认。")

    def export(self) -> None:
        path = self.candidate_root / "reports" / "user-validation-redacted.json"
        try:
            export_redacted_report(self.report, path)
        except OSError as exc:
            self._show_error("报告导出失败", exc)
            return
        self.report["steps"]["report"] = "observed"
        self._refresh_steps()
        self.status.set(f"已导出脱敏报告：{path}")
        messagebox.showinfo("导出完成", str(path))

    def cleanup(self) -> None:
        if self._runtime is not None:
            self._runtime.close()
            self._runtime = None
        try:
            removed = cleanup_validation_data(self.candidate_root)
        except (OSError, ValueError) as exc:
            self._show_error("清理失败", exc)
            return
        self._binding = None
        self._plans.clear()
        self._runs.clear()
        self.report["binding"] = {
            "state": "not_started",
            "bound_private_count": 0,
            "bound_group_count": 0,
        }
        self._write_log(f"已清理 {len(removed)} 个候选临时路径；Credential Manager 凭据未删除。")
        self.status.set("候选临时数据已清理；凭据仍由 Credential Manager 管理。")
        self._refresh_steps()

    def close(self) -> None:
        if self._runtime is not None:
            self._runtime.close()
            self._runtime = None
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()

    def _refresh_steps(self) -> None:
        for step, status in self.report["steps"].items():
            if self.tree.exists(step):
                self.tree.item(step, values=(step, status))

    def _write_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"{datetime.now().strftime('%H:%M:%S')}  {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    @staticmethod
    def _set_text(widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    @staticmethod
    def _show_error(title: str, error: Exception) -> None:
        code = getattr(getattr(error, "error", None), "code", None) or getattr(error, "code", None)
        message = f"{code}: {error}" if code else str(error)
        messagebox.showerror(title, redact_value(message))

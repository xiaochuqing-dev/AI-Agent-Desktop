from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPainterPath, QRegion
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .api_client import DISPLAY_NAMES, SLOTS, GuiApiClient
from .pages import (
    CompletionPage,
    DashboardPage,
    DiagnosticsPage,
    GroupPage,
    PrivateActivationPage,
    TokenPage,
    WelcomePage,
    label,
)
from .state_store import GuiStateStore
from .theme import build_stylesheet
from .widgets import (
    ASSET_DIR,
    ApiRunner,
    GlassCard,
    GradientCanvas,
    QrDialog,
    RefreshSpinner,
    StepRail,
    TelegramLauncher,
    TitleBar,
)


class HelpRail(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(276)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        self.primary = GlassCard()
        self.primary_layout = QVBoxLayout(self.primary)
        self.primary_layout.setContentsMargins(18, 14, 18, 14)
        self.primary_layout.setSpacing(7)
        self.secondary = GlassCard()
        self.secondary_layout = QVBoxLayout(self.secondary)
        self.secondary_layout.setContentsMargins(18, 14, 18, 14)
        self.secondary_layout.setSpacing(6)
        root.addWidget(self.primary)
        root.addWidget(self.secondary)
        root.addStretch(1)
        self.set_step(0)

    @staticmethod
    def _clear(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def set_step(self, index: int) -> None:
        self._clear(self.primary_layout)
        self._clear(self.secondary_layout)
        content = [
            (
                "★  你需要准备什么",
                [
                    ("3 个 Token", "从 BotFather 获取"),
                    ("可以访问 Telegram", "稍后会打开私聊"),
                    ("已创建好 3 个 Bot", "Hermes、Claude Code、Codex"),
                ],
                "?  如何获取 Token",
                "打开 Telegram 搜索 @BotFather，发送 /newbot 或选择已有 Bot，然后复制 Token。",
            ),
            (
                "★  这一页你要做什么",
                [
                    ("1  打开 Telegram", "点击每一行的按钮"),
                    ("2  点一次 Start", "在 Bot 私聊里点击"),
                    ("3  回到这里等待", "状态会自动更新"),
                ],
                "💡  提示",
                "不需要填写 Telegram 用户 ID。手机扫码也可以完成激活。",
            ),
            (
                "★  你要做什么",
                [
                    ("创建或打开一个群", "在 Telegram 中操作"),
                    ("加入 3 个 Bot", "全部加入同一个群"),
                    ("回到这里检测", "软件会自动识别"),
                ],
                "?  说明",
                "这里不需要填写 Group ID，也不会读取你的群列表或聊天历史。",
            ),
            (
                "★  这一页发生了什么",
                [
                    ("生成连接配置", "按当前绑定自动生成"),
                    ("检查 Agent 与 Runtime", "状态异常会提示处理"),
                    ("聊天验证需确认", "不会自动发送消息"),
                ],
                "?  如果遇到问题",
                "可以刷新、返回或打开详细诊断。不会自动发送消息。",
            ),
        ][index]
        title, items, secondary_title, secondary_body = content
        self.primary_layout.addWidget(label(title, "CardTitle"))
        for item_title, detail in items:
            self.primary_layout.addWidget(label(item_title, "CardTitle"))
            self.primary_layout.addWidget(label(detail, "SmallText"))
        self.primary_layout.addStretch(1)
        self.secondary_layout.addWidget(label(secondary_title, "CardTitle"))
        self.secondary_layout.addWidget(label(secondary_body, "BodyText"))
        self.secondary_layout.addStretch(1)


class WizardShell(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 28)
        root.setSpacing(16)
        content = QHBoxLayout()
        content.setSpacing(28)
        self.rail = StepRail()
        content.addWidget(self.rail)
        self.pages = QStackedWidget()
        self.token = TokenPage()
        self.private = PrivateActivationPage()
        self.group = GroupPage()
        self.completion = CompletionPage()
        for page in (self.token, self.private, self.group, self.completion):
            self.pages.addWidget(page)
        content.addWidget(self.pages, 1)
        self.help = HelpRail()
        content.addWidget(self.help)
        root.addLayout(content, 1)

        footer = QFrame()
        footer.setObjectName("FooterBar")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(258, 0, 304, 0)
        footer_layout.setSpacing(18)
        self.back = QPushButton("‹  返回上一步")
        self.back.setObjectName("SecondaryButton")
        self.aux = QPushButton("⌁  检查状态")
        self.aux.setObjectName("SecondaryButton")
        self.next = QPushButton("继续下一步  ›")
        self.next.setObjectName("PrimaryButton")
        footer_layout.addWidget(self.back)
        footer_layout.addWidget(self.aux)
        footer_layout.addWidget(self.next)
        root.addWidget(footer)
        self.set_step(0)

    def set_step(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.rail.set_active(index)
        self.help.set_step(index)
        self.back.setText("‹  返回欢迎页" if index == 0 else "‹  返回上一步")
        self.aux.setText(
            ["⌁  检测 Token 格式", "↻  检查激活状态", "↻  重新检测", "查看配置说明"][index]
        )
        self.next.setText(
            ["继续下一步  ›", "继续下一步  ›", "继续下一步  ›", "🚀  开始使用"][index]
        )


class MainWindow(QMainWindow):
    def __init__(self, client: GuiApiClient, *, demo_mode: bool = False) -> None:
        super().__init__()
        self.client = client
        self.store = GuiStateStore(client)
        self.runner = ApiRunner()
        self.demo_mode = demo_mode
        self.current_step = 0
        self._snapshot: dict[str, Any] = {}
        self._binding_poll_in_progress = False
        self._last_auto_poll_error: str | None = None
        self.setWindowTitle("AI Agent Desktop")
        self.setWindowIcon(QIcon(str(ASSET_DIR / "app_icon.ico")))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(1180, 680)
        self.resize(1280, 720)
        self.setStyleSheet(build_stylesheet())

        canvas = GradientCanvas()
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)
        self.title_bar = TitleBar(self, demo_mode=demo_mode)
        canvas_layout.addWidget(self.title_bar)
        self.root_stack = QStackedWidget()
        self.welcome = WelcomePage()
        self.wizard = WizardShell()
        self.dashboard = DashboardPage()
        self.diagnostics_page = DiagnosticsPage()
        self.root_stack.addWidget(self.welcome)
        self.root_stack.addWidget(self.wizard)
        self.root_stack.addWidget(self.dashboard)
        self.root_stack.addWidget(self.diagnostics_page)
        canvas_layout.addWidget(self.root_stack, 1)
        self.setCentralWidget(canvas)

        self.spinner = RefreshSpinner(self.title_bar.refresh)
        self.toast = QLabel(canvas)
        self.toast.setWordWrap(True)
        self.toast.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.toast.hide()
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(self.toast.hide)
        self.binding_poll_timer = QTimer(self)
        self.binding_poll_timer.setInterval(6000)
        self.binding_poll_timer.timeout.connect(self._auto_poll_binding)
        self._wire_events()
        QTimer.singleShot(80, self.initial_refresh)

    def _wire_events(self) -> None:
        self.title_bar.refresh_requested.connect(self.refresh_all)
        self.welcome.start_requested.connect(lambda: self.show_wizard(0))
        self.welcome.help_requested.connect(self.show_help_dialog)
        self.wizard.back.clicked.connect(self.go_back)
        self.wizard.next.clicked.connect(self.go_next)
        self.wizard.aux.clicked.connect(self.aux_action)
        self.wizard.private.open_requested.connect(self.open_private)
        self.wizard.private.qr_requested.connect(self.show_qr)
        self.wizard.private.poll_requested.connect(self.poll_binding)
        self.wizard.group.open_requested.connect(self.open_group)
        self.wizard.group.add_requested.connect(self.open_group)
        self.wizard.group.detect_requested.connect(self.poll_binding)
        self.wizard.completion.start_requested.connect(self.show_dashboard)
        self.wizard.completion.live_test_requested.connect(self.confirm_live_test)
        self.wizard.completion.skip_live_test_requested.connect(self.skip_live_test)
        self.wizard.completion.install_guide_requested.connect(self.open_external_url)
        self.wizard.completion.cc_switch_requested.connect(self.open_cc_switch)
        self.dashboard.reconfigure_requested.connect(lambda: self.show_wizard(0))
        self.dashboard.diagnostics_requested.connect(self.show_diagnostics)
        self.dashboard.refresh_requested.connect(self.refresh_all)
        self.dashboard.live_test_requested.connect(self.confirm_live_test)
        self.diagnostics_page.back_requested.connect(self.show_dashboard)

    def initial_refresh(self) -> None:
        self._run(self.store.refresh, self._initial_snapshot)

    def _initial_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.apply_snapshot(snapshot)
        if snapshot.get("onboarding_complete"):
            self.show_dashboard()
        elif int(snapshot.get("current_step", 0) or 0) >= 2:
            # The onboarding snapshot identifies the server-owned session, but
            # intentionally omits one-time links.  Reissue links for that
            # active session before polling; only create a new session when no
            # resumable session exists at all.
            target_step = min(int(snapshot.get("current_step", 2)) - 1, 3)
            self.show_wizard(target_step)
            if target_step in {1, 2} and not snapshot.get("binding_session"):
                session_id = (snapshot.get("binding") or {}).get("session_id")
                if session_id:
                    self.binding_poll_timer.stop()
                    self._run(
                        lambda: self.store.resume_binding(str(session_id)),
                        lambda resumed: self._binding_resumed(resumed, target_step),
                    )
                else:
                    self._run(self.store.begin_binding, self._binding_started)
        else:
            self.root_stack.setCurrentWidget(self.welcome)

    def _binding_resumed(self, snapshot: dict[str, Any], target_step: int) -> None:
        self.apply_snapshot(snapshot)
        self.show_wizard(target_step)
        self.show_toast("已恢复当前 Telegram 绑定进度，并生成新的短时链接。")

    def _run(self, function, on_success, *, busy_button: QPushButton | None = None) -> None:
        if busy_button is not None:
            busy_button.setEnabled(False)

        def finished(result):
            if busy_button is not None:
                busy_button.setEnabled(True)
            on_success(result)

        def failed(message: str, code: str):
            if busy_button is not None:
                busy_button.setEnabled(True)
            if self.current_step == 3:
                self.wizard.completion.set_failure(message)
                self.wizard.next.setText("重试配置  ›")
            self.show_toast(message, error=True)

        self.runner.run(function, finished, failed)

    def refresh_all(self) -> None:
        if not self.title_bar.refresh.isEnabled():
            return
        self.spinner.start()

        def done(snapshot):
            self.spinner.stop()
            self.apply_snapshot(snapshot)
            self.show_toast("状态已刷新")

        def failed(message: str, code: str):
            self.spinner.stop()
            self.dashboard.set_unknown()
            self.show_toast("状态待确认：" + message, error=True)

        self.runner.run(self.store.refresh, done, failed)

    def apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._snapshot = snapshot
        self.wizard.private.apply_snapshot(snapshot)
        self.wizard.group.apply_snapshot(snapshot)
        self.wizard.completion.apply_snapshot(snapshot)
        dashboard_snapshot = dict(snapshot.get("dashboard") or snapshot)
        # Keep binding progress from the onboarding model alongside the
        # dashboard read model so chat pills never imply live-message proof.
        dashboard_snapshot["agents"] = snapshot.get("agents", dashboard_snapshot.get("agents", []))
        dashboard_snapshot.setdefault("recent_issues", [])
        self.dashboard.apply_snapshot(dashboard_snapshot)

    def show_wizard(self, step: int) -> None:
        self.current_step = max(0, min(3, step))
        self.wizard.set_step(self.current_step)
        self.root_stack.setCurrentWidget(self.wizard)
        self._sync_binding_polling()

    def go_back(self) -> None:
        if self.current_step == 0:
            self.binding_poll_timer.stop()
            self.root_stack.setCurrentWidget(self.welcome)
            return
        self.show_wizard(self.current_step - 1)

    def go_next(self) -> None:
        if self.current_step == 0:
            tokens = self.wizard.token.collect_tokens()

            def saved(snapshot):
                self.wizard.token.clear_tokens()
                self.apply_snapshot(snapshot)
                self._run(
                    self.store.begin_binding, self._binding_started, busy_button=self.wizard.next
                )

            self._run(lambda: self.store.save_tokens(tokens), saved, busy_button=self.wizard.next)
            return
        if self.current_step == 1:
            if self._snapshot.get("binding", {}).get("bound_private_count", 0) < 3:
                self.poll_binding()
                return
            self.show_wizard(2)
            return
        if self.current_step == 2:
            if self._snapshot.get("binding", {}).get("bound_group_count", 0) < 3:
                self.poll_binding()
                return
            self.show_wizard(3)
            self._run(
                self.store.complete_configuration,
                self._configuration_complete,
                busy_button=self.wizard.next,
            )
            return
        if self._snapshot.get("onboarding_complete"):
            self.show_dashboard()
            return
        self._run(
            self.store.complete_configuration,
            self._configuration_complete,
            busy_button=self.wizard.next,
        )

    def aux_action(self) -> None:
        if self.current_step == 0:
            values = self.wizard.token.collect_tokens()
            missing = [
                DISPLAY_NAMES[slot] for slot, value in values.items() if len(value.strip()) < 12
            ]
            if missing:
                self.show_toast("这些 Token 还不完整：" + "、".join(missing), error=True)
            else:
                self.show_toast("格式检查通过，继续后会调用 Telegram getMe 验证。")
        elif self.current_step in {1, 2}:
            self.poll_binding()
        else:
            self.show_help_dialog()

    def _binding_started(self, snapshot: dict[str, Any]) -> None:
        self.apply_snapshot(snapshot)
        self.show_wizard(1)
        self.show_toast("Bot 身份已确认，请打开 Telegram 点击 Start。")

    def poll_binding(self) -> None:
        self._start_binding_poll(announce=True)

    def _auto_poll_binding(self) -> None:
        if self.root_stack.currentWidget() is not self.wizard or self.current_step not in {1, 2}:
            self.binding_poll_timer.stop()
            return
        self._start_binding_poll(announce=False)

    def _start_binding_poll(self, *, announce: bool) -> None:
        if self._binding_poll_in_progress:
            return
        self._binding_poll_in_progress = True
        if announce:
            self.wizard.aux.setEnabled(False)

        def done(snapshot: dict[str, Any]) -> None:
            self._binding_poll_in_progress = False
            self.wizard.aux.setEnabled(True)
            self._last_auto_poll_error = None
            self._sync_binding_polling()
            self._binding_polled(snapshot, announce=announce)

        def failed(message: str, code: str) -> None:
            self._binding_poll_in_progress = False
            self.wizard.aux.setEnabled(True)
            if announce:
                self.show_toast(message, error=True)
                return
            if code != self._last_auto_poll_error:
                self._last_auto_poll_error = code
                self.show_toast("自动检测已暂停：" + message, error=True)
            self.binding_poll_timer.stop()

        self.runner.run(self.store.poll_binding, done, failed)

    def _binding_polled(self, snapshot: dict[str, Any], *, announce: bool = True) -> None:
        previous_private = self._snapshot.get("binding", {}).get("bound_private_count", 0)
        previous_group = self._snapshot.get("binding", {}).get("bound_group_count", 0)
        self.apply_snapshot(snapshot)
        private_count = snapshot.get("binding", {}).get("bound_private_count", 0)
        group_count = snapshot.get("binding", {}).get("bound_group_count", 0)
        if self.current_step == 1 and private_count == 3:
            if announce or previous_private < 3:
                self.show_toast("3 个私聊都已激活，可以继续下一步。")
        elif self.current_step == 2 and group_count == 3:
            if announce or previous_group < 3:
                self.show_toast("已识别到同一个群，可以继续下一步。")
        elif announce:
            count = private_count if self.current_step == 1 else group_count
            self.show_toast(f"当前已完成 {count}/3，请完成 Telegram 中的操作后再检查。")

    def _sync_binding_polling(self) -> None:
        if self.current_step in {1, 2}:
            if not self.binding_poll_timer.isActive():
                self.binding_poll_timer.start()
        else:
            self.binding_poll_timer.stop()

    def open_private(self, slot: str) -> None:
        deep_link = self.wizard.private.deep_link(slot)
        if not deep_link:
            self._run(
                self.store.begin_binding,
                lambda snapshot: self._open_private_after_binding(snapshot, slot),
            )
            return
        if not TelegramLauncher.open_deep_link(deep_link):
            TelegramLauncher.open_download()
            self.show_toast("未检测到可用的 Telegram 客户端，已打开官方下载页。", error=True)

    def show_qr(self, slot: str) -> None:
        deep_link = self.wizard.private.deep_link(slot)
        if not deep_link:
            self._run(
                self.store.begin_binding,
                lambda snapshot: self._show_qr_after_binding(snapshot, slot),
            )
            return
        username = next(
            (
                item.get("bot_username")
                for item in self._snapshot.get("agents", [])
                if item.get("slot") == slot
            ),
            f"{slot}_bot",
        )
        binding = self._snapshot.get("binding_session") or self._snapshot.get("binding") or {}
        dialog = QrDialog(
            DISPLAY_NAMES[slot],
            username or f"{slot}_bot",
            deep_link,
            self,
            expires_at=binding.get("expires_at"),
        )
        dialog.show()
        self._qr_dialog = dialog

    def _open_private_after_binding(self, snapshot: dict[str, Any], slot: str) -> None:
        self.apply_snapshot(snapshot)
        self.open_private(slot)

    def _show_qr_after_binding(self, snapshot: dict[str, Any], slot: str) -> None:
        self.apply_snapshot(snapshot)
        self.show_qr(slot)

    def open_group(self, selected_slot: str | None = None) -> None:
        slots = (selected_slot,) if selected_slot else SLOTS
        for slot in slots:
            link = self.wizard.group.deep_link(slot)
            if link and TelegramLauncher.open_deep_link(link, group=True):
                return
            private_link = self.wizard.private.deep_link(slot)
            if not private_link:
                continue
            parsed = urlparse(private_link)
            query = parse_qs(parsed.query)
            payload = (query.get("start") or [""])[0]
            group_url = urlunparse(parsed._replace(query=urlencode({"startgroup": payload})))
            if TelegramLauncher.open_deep_link(group_url, group=True):
                return
        TelegramLauncher.open_download()

    def _configuration_complete(self, snapshot: dict[str, Any]) -> None:
        self.apply_snapshot(snapshot)
        self.wizard.completion.set_ready(
            chat_verified=snapshot.get("chat_health") == "live_verified"
        )
        self.wizard.next.setText("🚀  开始使用")
        self.show_toast("基础配置已完成。聊天验证仍需你明确确认。")

    def confirm_live_test(self) -> None:
        if not self._snapshot.get("onboarding_complete"):
            self.show_toast("请先完成 Agent、配置和运行环境检查。", error=True)
            return
        answer = QMessageBox.question(
            self,
            "确认真实聊天验证",
            "将分别向三个 Bot 的私聊和群聊发送一条短测试消息，共 6 条。\n\n"
            "每条链路最多发送 1 条，不会自动重复发送。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.show_toast("已取消，没有发送测试消息。")
            return
        self.wizard.completion.set_live_test_running()

        def done(snapshot: dict[str, Any]) -> None:
            self.apply_snapshot(snapshot)
            health = snapshot.get("chat_health")
            if health == "live_verified":
                self.wizard.completion.set_ready(chat_verified=True)
                self.show_toast("六条聊天链路已验证。")
            else:
                self.wizard.completion.set_failure(
                    "聊天验证尚未全部完成。不会自动重发，请查看各链路状态后按需重新确认。"
                )
                self.show_toast("聊天验证未全部通过，不会自动重发。", error=True)

        self._run(lambda: self.store.run_live_test(confirmation=True), done)

    def skip_live_test(self) -> None:
        if self._snapshot.get("onboarding_complete"):
            self.show_toast("基础配置已完成；聊天保持“待验证”，以后可从 Dashboard 验证。")
            self.show_dashboard()

    def open_external_url(self, url: str) -> None:
        if not QDesktopServices.openUrl(QUrl(url)):
            self.show_toast("无法打开安装说明，请稍后重试。", error=True)

    def open_cc_switch(self) -> None:
        if self._snapshot.get("cc_switch_openable"):
            self._run(
                self.client.open_cc_switch,
                lambda _result: self.show_toast("已打开 CC Switch。"),
            )
            return
        self.open_external_url("https://github.com/farion1231/cc-switch/releases")

    def show_dashboard(self) -> None:
        self.binding_poll_timer.stop()
        self.root_stack.setCurrentWidget(self.dashboard)
        self.refresh_all()

    def show_diagnostics(self) -> None:
        self.binding_poll_timer.stop()
        self.root_stack.setCurrentWidget(self.diagnostics_page)
        self._run(self.client.diagnostics, self.diagnostics_page.apply_diagnostics)

    def show_help_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("配置说明")
        dialog.setWindowIcon(QIcon(str(ASSET_DIR / "app_icon.ico")))
        dialog.setMinimumSize(560, 420)
        dialog.setStyleSheet(build_stylesheet() + "QDialog{background:#EEF1FD;}")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.addWidget(label("准备事项", "PageTitle"))
        layout.addWidget(
            label(
                "1. 在 BotFather 创建 Hermes、Claude Code、Codex 三个 Bot。\n\n2. 准备好三个 Token。\n\n3. 能够打开 Telegram，并在三个 Bot 私聊里点击 Start。\n\n4. 创建或使用一个群，把三个 Bot 加入同一个群。\n\n后面的连接配置会由 AI Agent Desktop 自动处理。",
                "BodyText",
            )
        )
        layout.addStretch(1)
        close = QPushButton("知道了")
        close.setObjectName("PrimaryButton")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def show_toast(self, message: str, *, error: bool = False) -> None:
        self.toast.setText(message)
        self.toast.setStyleSheet(
            "background:rgba(68,77,118,225);color:white;border-radius:10px;padding:11px 18px;font-size:14px;"
            if not error
            else "background:rgba(181,77,88,230);color:white;border-radius:10px;padding:11px 18px;font-size:14px;"
        )
        self.toast.adjustSize()
        width = min(max(self.toast.width(), 360), self.width() - 80)
        self.toast.resize(width, max(42, self.toast.height()))
        self.toast.move((self.width() - width) // 2, self.height() - self.toast.height() - 24)
        self.toast.raise_()
        self.toast.show()
        self.toast_timer.start(3600)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.isMaximized():
            self.clearMask()
        else:
            path = QPainterPath()
            path.addRoundedRect(self.rect(), 15, 15)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast.move(
                (self.width() - self.toast.width()) // 2, self.height() - self.toast.height() - 24
            )

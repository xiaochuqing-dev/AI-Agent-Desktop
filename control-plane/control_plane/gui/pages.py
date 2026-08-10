from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .api_client import DISPLAY_NAMES, SLOTS
from .widgets import AgentIcon, GlassCard, StatusChip


def label(text: str, object_name: str = "BodyText") -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(object_name)
    widget.setWordWrap(True)
    return widget


class WelcomePage(QWidget):
    start_requested = Signal()
    help_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(42, 34, 42, 24)
        root.setSpacing(18)

        title = label("欢迎使用 AI Agent Desktop", "WelcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)
        subtitle = label(
            "只需要几个简单步骤，就能把 Hermes、Claude Code 和 Codex 连接到 Telegram，后面的配置会由我们自动完成。",
            "Subtitle",
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(subtitle)

        cards = QHBoxLayout()
        cards.setSpacing(24)
        quick = GlassCard(strong=True)
        quick.setMinimumHeight(330)
        quick_layout = QVBoxLayout(quick)
        quick_layout.setContentsMargins(24, 22, 24, 20)
        heading = QHBoxLayout()
        heading.addWidget(label("🚀", "CardTitle"))
        heading.addWidget(label("快速开始", "CardTitle"))
        heading.addStretch(1)
        quick_layout.addLayout(heading)
        quick_layout.addWidget(label("只需四个简单步骤，我们会一步步帮你完成。"))

        steps = QHBoxLayout()
        steps.setSpacing(14)
        step_specs = [
            ("1", "填写 3 个\nBot Token", "输入 Hermes、Claude Code 和 Codex 的 Bot Token。"),
            ("2", "激活 3 个\n私聊", "分别打开 3 个 Bot 私聊并点击一次 Start。"),
            ("3", "加入同一个\n群", "把 3 个 Bot 全部加入同一个 Telegram 群。"),
            ("4", "等待自动\n完成", "我们会自动检查并完成剩余配置。"),
        ]
        for index, (number, text_value, detail_text) in enumerate(step_specs):
            column = QVBoxLayout()
            column.setSpacing(8)
            tile = QFrame()
            tile.setObjectName("GlassCard")
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(12, 10, 12, 10)
            tile.setMinimumHeight(78)
            badge = QLabel(number)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(30, 30)
            badge.setStyleSheet(
                "background:#4F83FA;color:white;border-radius:15px;font-weight:700;"
            )
            tile_layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignHCenter)
            tile_layout.addWidget(
                label(text_value, "BodyText"), alignment=Qt.AlignmentFlag.AlignHCenter
            )
            tile.setMinimumWidth(132)
            column.addWidget(tile)
            detail = label(detail_text, "SmallText")
            detail.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            detail.setMinimumHeight(42)
            column.addWidget(detail)
            steps.addLayout(column, 1)
            if index < len(step_specs) - 1:
                connector = QFrame()
                connector.setFixedSize(14, 1)
                connector.setStyleSheet(
                    "QFrame{border:none;border-top:1px dashed rgba(79,131,250,120);}"
                )
                connector.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                steps.addWidget(connector, alignment=Qt.AlignmentFlag.AlignVCenter)
        quick_layout.addLayout(steps)
        quick_layout.addStretch(1)
        cards.addWidget(quick, 7)

        result_card = GlassCard(strong=True)
        result_card.setMinimumHeight(300)
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(24, 22, 24, 18)
        result_layout.addWidget(label("✦   你将完成什么", "CardTitle"))
        for icon, title_text, detail_text_value in [
            ("➤", "连接 Telegram", "建立安全的 Telegram 连接。"),
            ("◆", "让 3 个 Bot 可以聊天", "让 Hermes、Claude Code 和 Codex 在群里正常对话。"),
            ("✓", "自动检查 Agent", "确认三个 Agent 都已准备好。"),
            ("●", "自动完成后续配置", "所有配置自动完成，无需手动操作。"),
        ]:
            row = QHBoxLayout()
            icon_label = QLabel(icon)
            icon_label.setFixedWidth(30)
            icon_label.setStyleSheet("font-size:20px;color:#5968E8;")
            row.addWidget(icon_label)
            text_box = QVBoxLayout()
            text_box.setSpacing(1)
            text_box.addWidget(label(title_text, "CardTitle"))
            text_box.addWidget(label(detail_text_value, "SmallText"))
            row.addLayout(text_box, 1)
            result_layout.addLayout(row)
        result_layout.addStretch(1)
        cards.addWidget(result_card, 3)
        root.addLayout(cards, 1)

        actions = QHBoxLayout()
        actions.setSpacing(20)
        start = QPushButton("🚀  开始快速配置")
        start.setObjectName("PrimaryButton")
        start.setMinimumWidth(312)
        start.clicked.connect(self.start_requested)
        help_button = QPushButton("查看配置说明")
        help_button.setObjectName("SecondaryButton")
        help_button.setMinimumWidth(264)
        help_button.clicked.connect(self.help_requested)
        actions.addStretch(1)
        actions.addWidget(start)
        actions.addWidget(help_button)
        actions.addStretch(1)
        root.addLayout(actions)
        foot = label("✓  整个过程大约需要 5–10 分钟，我们会一步步引导你完成。", "SmallText")
        foot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(foot)


class TokenPage(QWidget):
    submit_requested = Signal()
    back_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)
        root.addWidget(label("录入 3 个 Bot Token", "PageTitle"))
        root.addWidget(
            label(
                "请从 BotFather 获取 Hermes、Claude Code 和 Codex 的 Token。\n我们会把它们安全保存到本机。",
                "Subtitle",
            )
        )
        body = QHBoxLayout()
        body.setSpacing(28)
        form = GlassCard(strong=True)
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(28, 22, 28, 18)
        self.fields: dict[str, QLineEdit] = {}
        for slot in SLOTS:
            row = QVBoxLayout()
            row.setSpacing(7)
            row.addWidget(label(f"{DISPLAY_NAMES[slot]} Bot Token", "CardTitle"))
            input_row = QHBoxLayout()
            field = QLineEdit()
            field.setObjectName("TokenInput")
            field.setPlaceholderText("粘贴 BotFather 提供的 Token")
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setClearButtonEnabled(True)
            self.fields[slot] = field
            input_row.addWidget(field, 1)
            paste = QPushButton("粘贴")
            paste.setObjectName("InlineButton")
            paste.clicked.connect(
                lambda _checked=False, target=field: target.setText(QApplication.clipboard().text())
            )
            eye = QPushButton("◉")
            eye.setObjectName("InlineButton")
            eye.setFixedWidth(48)
            eye.setToolTip("按住临时显示 Token")
            eye.pressed.connect(lambda target=field: target.setEchoMode(QLineEdit.EchoMode.Normal))
            eye.released.connect(
                lambda target=field: target.setEchoMode(QLineEdit.EchoMode.Password)
            )
            field.editingFinished.connect(
                lambda target=field: target.setEchoMode(QLineEdit.EchoMode.Password)
            )
            input_row.addWidget(paste)
            input_row.addWidget(eye)
            row.addLayout(input_row)
            form_layout.addLayout(row)
            if slot != SLOTS[-1]:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setStyleSheet("color:rgba(197,210,236,110);")
                form_layout.addWidget(line)
        security = QHBoxLayout()
        security.addWidget(label("✓", "CardTitle"))
        security.addWidget(label("安全存储到 Windows Credential Manager", "SmallText"))
        security.addStretch(1)
        form_layout.addSpacing(4)
        form_layout.addLayout(security)
        body.addWidget(form, 7)

        # The fixed WizardShell already provides the right-side preparation/help
        # rail. Keeping the token form as the sole center panel preserves the
        # proportions of the reference layout and avoids duplicate guidance.
        root.addLayout(body, 1)

    def collect_tokens(self) -> dict[str, str]:
        return {slot: field.text() for slot, field in self.fields.items()}

    def clear_tokens(self) -> None:
        for field in self.fields.values():
            field.clear()


class PrivateActivationPage(QWidget):
    qr_requested = Signal(str)
    open_requested = Signal(str)
    poll_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addWidget(label("激活 3 个私聊", "PageTitle"))
        root.addWidget(
            label(
                "分别打开 Hermes、Claude Code 和 Codex 的 Telegram 私聊，并点击一次 Start。\n我们会自动识别激活状态。",
                "Subtitle",
            )
        )
        self.rows: dict[str, dict[str, Any]] = {}
        card = GlassCard(strong=True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 12, 22, 12)
        for slot in SLOTS:
            row = QFrame()
            row.setObjectName("BotRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 10, 4, 10)
            row_layout.setSpacing(12)
            row_layout.addWidget(AgentIcon(slot))
            identity = QVBoxLayout()
            identity.setSpacing(2)
            name = label(DISPLAY_NAMES[slot], "CardTitle")
            username = label("等待 Bot 身份确认", "SmallText")
            identity.addWidget(name)
            identity.addWidget(username)
            row_layout.addLayout(identity, 1)
            status = StatusChip("等待激活", "warning")
            row_layout.addWidget(status)
            open_button = QPushButton("➤  打开 Telegram")
            open_button.setObjectName("TelegramButton")
            open_button.clicked.connect(
                lambda _checked=False, value=slot: self.open_requested.emit(value)
            )
            row_layout.addWidget(open_button)
            qr = QPushButton("▦")
            qr.setObjectName("QrButton")
            qr.setToolTip("手机扫码激活")
            qr.clicked.connect(lambda _checked=False, value=slot: self.qr_requested.emit(value))
            row_layout.addWidget(qr)
            layout.addWidget(row)
            self.rows[slot] = {
                "username": username,
                "status": status,
                "open": open_button,
                "qr": qr,
            }
        info = QFrame()
        info_layout = QHBoxLayout(info)
        info_layout.setContentsMargins(8, 10, 8, 8)
        info_layout.addWidget(label("ⓘ", "CardTitle"))
        info_layout.addWidget(
            label("如果电脑没有安装 Telegram，也可以直接用手机扫码完成激活。", "SmallText")
        )
        layout.addWidget(info)
        root.addWidget(card, 1)

    def apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        for agent in snapshot.get("agents", []):
            slot = agent.get("slot")
            if slot not in self.rows:
                continue
            row = self.rows[slot]
            row["username"].setText(
                f"@{agent['bot_username']}" if agent.get("bot_username") else "等待 Bot 身份确认"
            )
            status = agent.get("private_status")
            if status == "bound":
                row["status"].set_status("已激活", "success")
            elif status == "rejected":
                row["status"].set_status("需要重新验证", "warning")
            else:
                row["status"].set_status("等待激活", "warning")
        session = snapshot.get("binding_session") or {}
        self.links = session.get("private_deep_links", {})

    def deep_link(self, slot: str) -> str | None:
        return getattr(self, "links", {}).get(slot)


class GroupPage(QWidget):
    open_requested = Signal()
    add_requested = Signal(str)
    detect_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addWidget(label("把 3 个 Bot 加入同一个群", "PageTitle"))
        root.addWidget(
            label(
                "创建一个 Telegram 群，或者使用你已有的群。然后把下面 3 个 Bot 全部加入进去，\n我们会自动识别。",
                "Subtitle",
            )
        )
        card = GlassCard(strong=True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 16, 22, 12)
        actions = QHBoxLayout()
        open_button = QPushButton("➤  打开 Telegram")
        open_button.setObjectName("SecondaryButton")
        open_button.clicked.connect(self.open_requested)
        detect = QPushButton("⌕  我已经加好了，开始检测")
        detect.setObjectName("PrimaryButton")
        detect.clicked.connect(self.detect_requested)
        actions.addWidget(open_button)
        actions.addStretch(1)
        actions.addWidget(detect)
        layout.addLayout(actions)
        self.rows: dict[str, dict[str, Any]] = {}
        for slot in SLOTS:
            row = QFrame()
            row.setObjectName("BotRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 10, 4, 10)
            row_layout.setSpacing(12)
            row_layout.addWidget(AgentIcon(slot))
            identity = QVBoxLayout()
            identity.setSpacing(2)
            identity.addWidget(label(DISPLAY_NAMES[slot], "CardTitle"))
            username = label("等待 Bot 身份确认", "SmallText")
            identity.addWidget(username)
            row_layout.addLayout(identity, 1)
            copy_button = QPushButton("复制用户名")
            copy_button.setObjectName("InlineButton")
            copy_button.clicked.connect(
                lambda _checked=False, value=slot: self.copy_username(value)
            )
            add_button = QPushButton("➤  通过 Telegram 添加")
            add_button.setObjectName("InlineButton")
            add_button.clicked.connect(
                lambda _checked=False, value=slot: self.add_requested.emit(value)
            )
            status = StatusChip("等待加入", "warning")
            row_layout.addWidget(copy_button)
            row_layout.addWidget(add_button)
            row_layout.addWidget(status)
            layout.addWidget(row)
            self.rows[slot] = {
                "username": username,
                "status": status,
                "copy": copy_button,
                "add": add_button,
            }
        self.group_info = QLabel("尚未识别到群")
        self.group_info.setObjectName("SmallText")
        self.group_info.setWordWrap(True)
        info = QFrame()
        info.setObjectName("GlassCard")
        info_layout = QHBoxLayout(info)
        info_layout.setContentsMargins(14, 12, 14, 12)
        info_layout.addWidget(QLabel("👥"))
        info_layout.addWidget(self.group_info, 1)
        layout.addWidget(info)
        root.addWidget(card, 1)

    def copy_username(self, slot: str) -> None:
        value = self.rows[slot]["username"].text()
        if value.startswith("@"):
            QApplication.clipboard().setText(value)

    def apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        for agent in snapshot.get("agents", []):
            slot = agent.get("slot")
            if slot not in self.rows:
                continue
            row = self.rows[slot]
            row["username"].setText(
                f"@{agent['bot_username']}" if agent.get("bot_username") else "等待 Bot 身份确认"
            )
            status = agent.get("group_status")
            if status == "bound":
                row["status"].set_status("已检测", "success")
            elif status == "rejected":
                row["status"].set_status("请重新添加", "warning")
            else:
                row["status"].set_status("等待加入", "warning")
        binding = snapshot.get("binding", {})
        session = snapshot.get("binding_session") or {}
        self.group_links = session.get("group_deep_links", {})
        if binding.get("bound_group_count") == 3 and binding.get("group_title"):
            self.group_info.setText(
                f"已识别到群：{binding['group_title']}\n三个 Bot 已加入同一个群"
            )
        else:
            count = binding.get("bound_group_count", 0)
            self.group_info.setText(
                f"正在等待群聊检测（{count}/3）\n把 3 个 Bot 加入同一个群后，点击开始检测。"
            )

    def deep_link(self, slot: str) -> str | None:
        return getattr(self, "group_links", {}).get(slot)


class CompletionPage(QWidget):
    retry_requested = Signal()
    live_test_requested = Signal()
    start_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addWidget(label("正在为你完成剩余配置", "PageTitle"))
        root.addWidget(
            label(
                "后面的连接和设置会由我们自动完成。你只需要等待一下，完成后就可以开始使用。",
                "Subtitle",
            )
        )
        card = GlassCard(strong=True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 16, 24, 14)
        self.checks: dict[str, tuple[QLabel, StatusChip]] = {}
        self.chat_pills: dict[tuple[str, str], QLabel] = {}
        items = [
            ("telegram", "检查 Telegram 连接", "➤"),
            ("agents", "检查 Hermes、Claude Code 和 Codex", "◇"),
            ("runtime", "准备运行环境", "▤"),
            ("configuration", "生成连接配置", "⚙"),
            ("chat", "检查聊天是否可用", "⋯"),
        ]
        for key, text_value, icon in items:
            row = QHBoxLayout()
            glyph = QLabel(icon)
            glyph.setFixedWidth(32)
            glyph.setStyleSheet("font-size:20px;color:#5868E8;")
            row.addWidget(glyph)
            row.addWidget(label(text_value, "CardTitle"), 1)
            status = StatusChip("等待", "neutral")
            row.addWidget(status)
            layout.addLayout(row)
            self.checks[key] = (glyph, status)
        root.addWidget(card)

        results = GlassCard()
        result_layout = QVBoxLayout(results)
        result_layout.setContentsMargins(22, 12, 22, 12)
        result_layout.addWidget(label("聊天结果", "CardTitle"))
        pills = QGridLayout()
        pills.setHorizontalSpacing(8)
        pills.setVerticalSpacing(6)
        for column in range(3):
            pills.setColumnStretch(column, 1)
        self.short_names = {"hermes": "Hermes", "claude": "Claude", "codex": "Codex"}
        pill_index = 0
        for slot in SLOTS:
            for kind, suffix in (("private", "私聊"), ("group", "群聊")):
                name = f"{self.short_names[slot]} {suffix}"
                pill = QLabel(f"{name}  ·  待确认")
                pill.setProperty("kind", "neutral")
                self.chat_pills[(slot, kind)] = pill
                pill.setObjectName("ChatPill")
                pill.setProperty("chat_slot", slot)
                pill.setProperty("chat_kind", kind)
                pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
                pill.setWordWrap(True)
                pill.setMinimumWidth(0)
                pill.setMinimumHeight(28)
                pill.setToolTip(f"{name}：待确认")
                pill.setStyleSheet(
                    "background:rgba(239,243,252,220);border:1px solid rgba(205,216,238,150);"
                    "border-radius:12px;padding:3px 4px;color:#5D6275;font-size:10px;"
                )
                pill.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                pills.addWidget(pill, pill_index // 3, pill_index % 3)
                pill_index += 1
        result_layout.addLayout(pills)
        root.addWidget(results)

        banner = QFrame()
        banner.setObjectName("SuccessBanner")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(14, 8, 14, 8)
        self.banner_text = label("配置完成后，你就可以开始使用了。", "BodyText")
        self.banner_text.setStyleSheet("color:#2B8050;font-size:15px;font-weight:600;")
        banner_layout.addWidget(self.banner_text)
        root.addWidget(banner)
        root.addStretch(1)

    def apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        for item in snapshot.get("checklist", []):
            key = item.get("key")
            if key not in self.checks:
                continue
            _glyph, status = self.checks[key]
            value = item.get("status")
            if value == "complete":
                status.set_status("完成", "success")
            elif value == "needs_action":
                status.set_status("需要处理", "warning")
            else:
                status.set_status("等待", "neutral")
        for agent in snapshot.get("agents", []):
            slot = agent.get("slot")
            if slot not in SLOTS:
                continue
            for kind, status_key in (("private", "private_status"), ("group", "group_status")):
                pill = self.chat_pills[(slot, kind)]
                if agent.get(status_key) == "bound":
                    name = f"{self.short_names[slot]} {'私聊' if kind == 'private' else '群聊'}"
                    pill.setText(f"{name}  ·  已绑定")
                    pill.setToolTip(f"{name}：已绑定")
                    pill.setStyleSheet(
                        "background:rgba(229,248,238,220);border:1px solid rgba(152,220,180,130);"
                        "border-radius:12px;padding:3px 4px;color:#2B8050;font-size:10px;"
                    )
                else:
                    name = f"{self.short_names[slot]} {'私聊' if kind == 'private' else '群聊'}"
                    pill.setText(f"{name}  ·  待确认")
                    pill.setToolTip(f"{name}：待确认")
                    pill.setStyleSheet(
                        "background:rgba(239,243,252,220);border:1px solid rgba(205,216,238,150);"
                        "border-radius:12px;padding:3px 4px;color:#5D6275;font-size:10px;"
                    )

    def set_failure(self, message: str) -> None:
        self.banner_text.setText(f"配置暂时没有完成：{message}\n可以点击重试配置，或打开详细诊断。")
        self.banner_text.setStyleSheet("color:#A94A55;font-size:15px;font-weight:600;")

    def set_ready(self) -> None:
        self.banner_text.setText("🎉  已准备完成，你现在可以开始使用了。")
        self.banner_text.setStyleSheet("color:#2B8050;font-size:15px;font-weight:600;")


class DashboardPage(QWidget):
    reconfigure_requested = Signal()
    diagnostics_requested = Signal()
    refresh_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(38, 28, 38, 26)
        root.setSpacing(18)
        top = QHBoxLayout()
        top.addLayout(QVBoxLayout())
        title_box = QVBoxLayout()
        title_box.addWidget(label("AI Agent Desktop", "PageTitle"))
        title_box.addWidget(label("你的 Telegram AI 编程团队状态", "Subtitle"))
        top.addLayout(title_box, 1)
        self.overall = StatusChip("状态待确认", "neutral")
        top.addWidget(self.overall, alignment=Qt.AlignmentFlag.AlignTop)
        root.addLayout(top)
        agents_card = GlassCard(strong=True)
        agents_layout = QHBoxLayout(agents_card)
        agents_layout.setContentsMargins(18, 18, 18, 18)
        self.agent_cards: dict[str, QLabel] = {}
        self.chat_pills: dict[tuple[str, str], QLabel] = {}
        for slot in SLOTS:
            card = GlassCard()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            line = QHBoxLayout()
            line.addWidget(AgentIcon(slot))
            line.addWidget(label(DISPLAY_NAMES[slot], "CardTitle"), 1)
            card_layout.addLayout(line)
            state = label("状态待确认", "BodyText")
            card_layout.addWidget(state)
            action = QPushButton("重新检查")
            action.setObjectName("InlineButton")
            action.clicked.connect(self.refresh_requested)
            card_layout.addWidget(action)
            agents_layout.addWidget(card, 1)
            self.agent_cards[slot] = state
        root.addWidget(agents_card)
        pills_card = GlassCard()
        pills_layout = QHBoxLayout(pills_card)
        pills_layout.setContentsMargins(18, 12, 18, 12)
        for slot in SLOTS:
            for kind, suffix in (("private", "私聊"), ("group", "群聊")):
                text_value = f"{DISPLAY_NAMES[slot]} {suffix}"
                chip = QLabel(f"{text_value}  ·  待确认")
                self.chat_pills[(slot, kind)] = chip
                chip.setStyleSheet(
                    "background:rgba(239,243,252,220);border:1px solid rgba(205,216,238,150);"
                    "border-radius:11px;padding:5px 10px;color:#5D6275;font-size:12px;"
                )
                pills_layout.addWidget(chip)
        pills_layout.addStretch(1)
        root.addWidget(pills_card)
        issue_card = GlassCard()
        issue_layout = QVBoxLayout(issue_card)
        issue_layout.setContentsMargins(18, 14, 18, 14)
        self.issue_text = label("最近没有需要处理的问题。", "BodyText")
        issue_layout.addWidget(self.issue_text)
        root.addWidget(issue_card)
        actions = QHBoxLayout()
        reconfigure = QPushButton("↻  重新运行快速配置")
        reconfigure.setObjectName("SecondaryButton")
        reconfigure.clicked.connect(self.reconfigure_requested)
        diagnostics = QPushButton("⌕  查看详细诊断")
        diagnostics.setObjectName("PrimaryButton")
        diagnostics.clicked.connect(self.diagnostics_requested)
        actions.addWidget(reconfigure)
        actions.addStretch(1)
        actions.addWidget(diagnostics)
        root.addLayout(actions)

    def apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        overall = snapshot.get("overall_status")
        if overall == "ready":
            self.overall.set_status("已准备", "success")
        elif overall == "needs_action":
            self.overall.set_status("需要处理", "warning")
        else:
            self.overall.set_status("状态待确认", "neutral")
        for agent in snapshot.get("agents", []):
            slot = agent.get("slot")
            state = self.agent_cards.get(slot)
            if state is not None:
                if agent.get("status") == "ready" or agent.get("identity_verified"):
                    state.setText(agent.get("user_message", "已准备好"))
                else:
                    state.setText(agent.get("user_message", "状态待确认"))
            if slot not in SLOTS:
                continue
            for kind, status_key in (("private", "private_status"), ("group", "group_status")):
                pill = self.chat_pills[(slot, kind)]
                suffix = "私聊" if kind == "private" else "群聊"
                if agent.get(status_key) == "bound":
                    pill.setText(f"{DISPLAY_NAMES[slot]} {suffix}  ·  已绑定")
                    pill.setStyleSheet(
                        "background:rgba(229,248,238,220);border:1px solid rgba(152,220,180,130);"
                        "border-radius:11px;padding:5px 10px;color:#2B8050;font-size:12px;"
                    )
                else:
                    pill.setText(f"{DISPLAY_NAMES[slot]} {suffix}  ·  待确认")
                    pill.setStyleSheet(
                        "background:rgba(239,243,252,220);border:1px solid rgba(205,216,238,150);"
                        "border-radius:11px;padding:5px 10px;color:#5D6275;font-size:12px;"
                    )
        issues = snapshot.get("recent_issues") or []
        self.issue_text.setText(issues[0] if issues else "最近没有需要处理的问题。")

    def set_unknown(self) -> None:
        self.overall.set_status("状态待确认", "neutral")
        for state in self.agent_cards.values():
            state.setText("状态待确认")
        for (slot, kind), pill in self.chat_pills.items():
            suffix = "私聊" if kind == "private" else "群聊"
            pill.setText(f"{DISPLAY_NAMES[slot]} {suffix}  ·  状态待确认")
            pill.setStyleSheet(
                "background:rgba(239,243,252,220);border:1px solid rgba(205,216,238,150);"
                "border-radius:11px;padding:5px 10px;color:#5D6275;font-size:12px;"
            )
        self.issue_text.setText("暂时无法读取最新状态，请点击刷新后重试。")


class DiagnosticsPage(QWidget):
    back_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(38, 28, 38, 26)
        root.setSpacing(16)
        root.addWidget(label("详细诊断", "PageTitle"))
        root.addWidget(
            label("这里显示用户可以理解的原因和下一步操作。技术细节只在需要时展开。", "Subtitle")
        )
        card = GlassCard(strong=True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        self.body = label("正在读取诊断…", "BodyText")
        layout.addWidget(self.body)
        root.addWidget(card, 1)
        back = QPushButton("‹  返回首页")
        back.setObjectName("SecondaryButton")
        back.clicked.connect(self.back_requested)
        root.addWidget(back, alignment=Qt.AlignmentFlag.AlignLeft)

    def apply_diagnostics(self, diagnostics: list[dict[str, Any]]) -> None:
        if not diagnostics:
            self.body.setText(
                "✓ 当前没有需要处理的问题。\n\n如果状态发生变化，可以点击顶部的刷新按钮重新读取。"
            )
            return
        lines = []
        for item in diagnostics:
            lines.append(
                f"• {item.get('user_message') or item.get('summary') or '需要进一步检查。'}"
            )
        self.body.setText("\n".join(lines))

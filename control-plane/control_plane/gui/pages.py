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
    skip_live_test_requested = Signal()
    install_guide_requested = Signal(str)
    cc_switch_requested = Signal()
    start_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        title = label("正在为你完成剩余配置", "PageTitle")
        title.setWordWrap(False)
        title.setStyleSheet("font-size:32px;")
        root.addWidget(title)
        subtitle = label(
            "后面的连接和设置会由我们自动完成。你只需要等待一下，完成后就可以开始使用。",
            "Subtitle",
        )
        subtitle.setStyleSheet("font-size:13px;")
        root.addWidget(subtitle)
        card = GlassCard(strong=True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 8, 18, 8)
        layout.setSpacing(1)
        self.checks: dict[str, tuple[QLabel, StatusChip]] = {}
        self.check_rows: list[QWidget] = []
        self.chat_pills: dict[tuple[str, str], QLabel] = {}
        items = [
            ("telegram", "检查 Telegram 连接", "➤"),
            ("agents", "检查 Hermes、Claude Code 和 Codex", "◇"),
            ("runtime", "准备运行环境", "▤"),
            ("configuration", "生成连接配置", "⚙"),
            ("chat", "检查聊天是否可用", "⋯"),
        ]
        for key, text_value, icon in items:
            row_widget = QWidget()
            row_widget.setFixedHeight(20)
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(7)
            glyph = QLabel(icon)
            glyph.setFixedWidth(20)
            glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            glyph.setStyleSheet("font-size:14px;color:#5868E8;")
            row.addWidget(glyph)
            check_label = QLabel(text_value)
            check_label.setStyleSheet("font-size:12px;font-weight:600;color:#111323;")
            row.addWidget(check_label, 1)
            status = StatusChip("等待", "neutral")
            status.setFixedHeight(18)
            status.setStyleSheet("padding:1px 7px;font-size:10px;border-radius:9px;")
            row.addWidget(status)
            layout.addWidget(row_widget)
            self.check_rows.append(row_widget)
            self.checks[key] = (glyph, status)
        root.addWidget(card)

        agents = GlassCard()
        agent_layout = QVBoxLayout(agents)
        agent_layout.setContentsMargins(18, 8, 18, 8)
        agent_layout.setSpacing(4)
        agent_header = QHBoxLayout()
        agent_title = QLabel("Agent 检测")
        agent_title.setStyleSheet("font-size:15px;font-weight:650;color:#111323;")
        agent_header.addWidget(agent_title)
        agent_header.addStretch(1)
        self.cc_switch_button = QPushButton("获取 CC Switch（可选）")
        self.cc_switch_button.setObjectName("CompactInlineButton")
        self.cc_switch_button.clicked.connect(self.cc_switch_requested)
        agent_header.addWidget(self.cc_switch_button)
        agent_layout.addLayout(agent_header)
        agent_statuses = QHBoxLayout()
        agent_statuses.setSpacing(12)
        self.agent_rows: dict[str, dict[str, Any]] = {}
        for slot in SLOTS:
            cell = QWidget()
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(0)
            name = QLabel(DISPLAY_NAMES[slot])
            name.setStyleSheet("font-size:12px;font-weight:650;color:#111323;")
            cell_layout.addWidget(name)
            state_row = QHBoxLayout()
            state_row.setContentsMargins(0, 0, 0, 0)
            state_row.setSpacing(5)
            state = QLabel("等待检测")
            state.setStyleSheet("color:#5D6275;font-size:11px;")
            state_row.addWidget(state, 1)
            guide = QPushButton("安装说明")
            guide.setObjectName("CompactInlineButton")
            guide.hide()
            guide.clicked.connect(
                lambda _checked=False, selected=slot: self._open_install_guide(selected)
            )
            state_row.addWidget(guide)
            cell_layout.addLayout(state_row)
            agent_statuses.addWidget(cell, 1)
            self.agent_rows[slot] = {"state": state, "guide": guide, "url": ""}
        agent_layout.addLayout(agent_statuses)
        root.addWidget(agents)

        results = GlassCard()
        result_layout = QVBoxLayout(results)
        result_layout.setContentsMargins(18, 8, 18, 8)
        result_layout.setSpacing(4)
        result_title = QLabel("聊天结果")
        result_title.setStyleSheet("font-size:15px;font-weight:650;color:#111323;")
        result_layout.addWidget(result_title)
        pills = QGridLayout()
        pills.setHorizontalSpacing(8)
        pills.setVerticalSpacing(4)
        for column in range(3):
            pills.setColumnStretch(column, 1)
        self.short_names = {"hermes": "Hermes", "claude": "Claude", "codex": "Codex"}
        pill_index = 0
        for slot in SLOTS:
            for kind, suffix in (("private", "私聊"), ("group", "群聊")):
                chat_name = f"{self.short_names[slot]} {suffix}"
                pill = QLabel(f"{chat_name}  ·  待确认")
                pill.setProperty("kind", "neutral")
                self.chat_pills[(slot, kind)] = pill
                pill.setObjectName("ChatPill")
                pill.setProperty("chat_slot", slot)
                pill.setProperty("chat_kind", kind)
                pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
                pill.setWordWrap(True)
                pill.setMinimumWidth(0)
                pill.setFixedHeight(22)
                pill.setToolTip(f"{chat_name}：待确认")
                pill.setStyleSheet(
                    "background:rgba(239,243,252,220);border:1px solid rgba(205,216,238,150);"
                    "border-radius:10px;padding:1px 4px;color:#5D6275;font-size:9px;"
                )
                pill.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                pills.addWidget(pill, pill_index // 3, pill_index % 3)
                pill_index += 1
        result_layout.addLayout(pills)
        root.addWidget(results)

        banner = QFrame()
        banner.setObjectName("SuccessBanner")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(12, 6, 12, 6)
        self.banner_text = label("配置完成后，你就可以开始使用了。", "BodyText")
        self.banner_text.setStyleSheet("color:#2B8050;font-size:13px;font-weight:600;")
        banner_layout.addWidget(self.banner_text)
        root.addWidget(banner)
        live_actions = QHBoxLayout()
        self.live_button = QPushButton("快速验证聊天")
        self.live_button.setObjectName("PrimaryButton")
        self.live_button.clicked.connect(self.live_test_requested)
        self.live_button.setEnabled(False)
        self.skip_live_button = QPushButton("以后再验证")
        self.skip_live_button.setObjectName("SecondaryButton")
        self.skip_live_button.clicked.connect(self.skip_live_test_requested)
        self.skip_live_button.setEnabled(False)
        live_actions.addWidget(self.live_button)
        live_actions.addWidget(self.skip_live_button)
        live_actions.addStretch(1)
        root.addLayout(live_actions)
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
            row = self.agent_rows[slot]
            version = f" · {agent['version']}" if agent.get("version") else ""
            if agent.get("acceptable"):
                row["state"].setText(f"已检测{version}")
                row["state"].setToolTip(f"{DISPLAY_NAMES[slot]} 已检测{version}")
                row["state"].setStyleSheet("color:#2B8050;font-size:11px;font-weight:600;")
                row["guide"].hide()
            else:
                message = agent.get("user_message") or "需要处理"
                row["state"].setText(message)
                row["state"].setToolTip(message)
                row["state"].setStyleSheet("color:#A86A20;font-size:11px;font-weight:600;")
                row["url"] = agent.get("official_install_url") or ""
                row["guide"].show()
        for link in snapshot.get("chat_links", []):
            slot = link.get("slot")
            kind = link.get("scope")
            if (slot, kind) not in self.chat_pills:
                continue
            self._set_chat_pill(
                slot,
                kind,
                link.get("health_status", "unknown"),
                link.get("binding_status", "pending"),
                link,
            )
        if not snapshot.get("chat_links"):
            for agent in snapshot.get("agents", []):
                slot = agent.get("slot")
                if slot not in SLOTS:
                    continue
                for kind, status_key in (
                    ("private", "private_status"),
                    ("group", "group_status"),
                ):
                    binding = "bound" if agent.get(status_key) == "bound" else "pending"
                    self._set_chat_pill(slot, kind, "unknown", binding, {})
        base_ready = bool(snapshot.get("onboarding_complete"))
        self.live_button.setEnabled(base_ready)
        self.skip_live_button.setEnabled(base_ready)
        self.cc_switch_button.setText(
            "打开 CC Switch（可选）"
            if snapshot.get("cc_switch_openable")
            else "获取 CC Switch（可选）"
        )

    def _open_install_guide(self, slot: str) -> None:
        url = str(self.agent_rows[slot].get("url") or "")
        if url:
            self.install_guide_requested.emit(url)

    def _set_chat_pill(
        self,
        slot: str,
        kind: str,
        health: str,
        binding: str,
        details: dict[str, Any],
    ) -> None:
        pill = self.chat_pills[(slot, kind)]
        name = f"{self.short_names[slot]} {'私聊' if kind == 'private' else '群聊'}"
        if health == "live_verified":
            text_value, color, background, border = (
                "已验证",
                "#2B8050",
                "229,248,238,220",
                "152,220,180,130",
            )
        elif health == "stale":
            text_value, color, background, border = (
                "需重新确认",
                "#A86A20",
                "255,245,220,230",
                "224,190,120,150",
            )
        elif health == "failed":
            text_value, color, background, border = (
                "验证失败",
                "#A94A55",
                "255,235,238,230",
                "226,153,164,150",
            )
        elif health == "ready_for_test":
            text_value, color, background, border = (
                "待验证",
                "#5969D8",
                "235,239,255,230",
                "164,178,238,150",
            )
        elif binding == "bound":
            text_value, color, background, border = (
                "已绑定",
                "#5D6275",
                "239,243,252,220",
                "205,216,238,150",
            )
        else:
            text_value, color, background, border = (
                "未绑定",
                "#5D6275",
                "239,243,252,220",
                "205,216,238,150",
            )
        pill.setText(f"{name}  ·  {text_value}")
        technical = [details.get("user_message", text_value)]
        for key, label_text in (
            ("correlation_id", "Correlation"),
            ("request_message_id", "Request"),
            ("response_message_id", "Response"),
            ("latency_ms", "Latency ms"),
        ):
            if details.get(key) is not None:
                technical.append(f"{label_text}: {details[key]}")
        pill.setToolTip("\n".join(str(item) for item in technical))
        pill.setStyleSheet(
            f"background:rgba({background});border:1px solid rgba({border});"
            f"border-radius:10px;padding:1px 4px;color:{color};font-size:9px;"
        )

    def set_live_test_running(self) -> None:
        self.live_button.setEnabled(False)
        self.skip_live_button.setEnabled(False)
        for (slot, kind), pill in self.chat_pills.items():
            name = f"{self.short_names[slot]} {'私聊' if kind == 'private' else '群聊'}"
            pill.setText(f"{name}  ·  发送中")
        self.banner_text.setText("正在逐条执行 6 项聊天验证，每条最多发送 1 条消息，不会自动重试。")

    def set_failure(self, message: str) -> None:
        self.banner_text.setText(f"配置暂时没有完成：{message}\n可以点击重试配置，或打开详细诊断。")
        self.banner_text.setStyleSheet("color:#A94A55;font-size:13px;font-weight:600;")

    def set_ready(self, *, chat_verified: bool = False) -> None:
        self.banner_text.setText(
            "🎉  六条聊天链路已验证，你现在可以开始使用了。"
            if chat_verified
            else "基础配置已完成。你可以快速验证聊天，或以后从 Dashboard 再验证。"
        )
        self.banner_text.setStyleSheet("color:#2B8050;font-size:13px;font-weight:600;")


class DashboardPage(QWidget):
    reconfigure_requested = Signal()
    diagnostics_requested = Signal()
    refresh_requested = Signal()
    live_test_requested = Signal()

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
        live_test = QPushButton("快速验证聊天")
        live_test.setObjectName("SecondaryButton")
        live_test.clicked.connect(self.live_test_requested)
        actions.addWidget(live_test)
        actions.addStretch(1)
        actions.addWidget(diagnostics)
        root.addLayout(actions)

    def apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        overall = snapshot.get("overall_status")
        if overall == "ready" and snapshot.get("chat_health") == "live_verified":
            self.overall.set_status("已验证", "success")
        elif overall == "ready":
            self.overall.set_status("基础配置完成", "neutral")
        elif overall == "needs_action":
            self.overall.set_status("需要处理", "warning")
        else:
            self.overall.set_status("状态待确认", "neutral")
        for agent in snapshot.get("agents", []):
            slot = agent.get("slot")
            state = self.agent_cards.get(slot)
            if state is not None:
                if agent.get("status") == "ready" or agent.get("acceptable"):
                    state.setText(agent.get("user_message", "已准备好"))
                else:
                    state.setText(agent.get("user_message", "状态待确认"))
        for link in snapshot.get("chat_links", []):
            slot = link.get("slot")
            kind = link.get("scope")
            if (slot, kind) not in self.chat_pills:
                continue
            pill = self.chat_pills[(slot, kind)]
            suffix = "私聊" if kind == "private" else "群聊"
            health = link.get("health_status")
            binding = link.get("binding_status")
            text_value = {
                "live_verified": "已验证",
                "ready_for_test": "待验证",
                "failed": "验证失败",
                "stale": "需重新确认",
            }.get(health, "已绑定" if binding == "bound" else "未绑定")
            pill.setText(f"{DISPLAY_NAMES[slot]} {suffix}  ·  {text_value}")
            success = health == "live_verified"
            pill.setStyleSheet(
                (
                    "background:rgba(229,248,238,220);border:1px solid rgba(152,220,180,130);"
                    "border-radius:11px;padding:5px 10px;color:#2B8050;font-size:12px;"
                )
                if success
                else (
                    "background:rgba(239,243,252,220);border:1px solid rgba(205,216,238,150);"
                    "border-radius:11px;padding:5px 10px;color:#5D6275;font-size:12px;"
                )
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

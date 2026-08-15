from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from PySide6.QtCore import (
    QObject,
    QPoint,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .icons import IconButton, icon

ASSET_DIR = Path(__file__).with_name("assets")


class GradientCanvas(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GradientCanvas")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = QLinearGradient(0, 0, self.width(), self.height())
        base.setColorAt(0.0, QColor("#E8E9FD"))
        base.setColorAt(0.48, QColor("#EEF2FD"))
        base.setColorAt(1.0, QColor("#D8E9FF"))
        painter.fillRect(self.rect(), base)

        pink = QRadialGradient(self.width() * 0.13, self.height() * 0.92, self.width() * 0.62)
        pink.setColorAt(0.0, QColor(246, 181, 255, 125))
        pink.setColorAt(1.0, QColor(246, 181, 255, 0))
        painter.fillRect(self.rect(), pink)

        blue = QRadialGradient(self.width() * 0.92, self.height() * 0.05, self.width() * 0.62)
        blue.setColorAt(0.0, QColor(118, 205, 255, 102))
        blue.setColorAt(1.0, QColor(118, 205, 255, 0))
        painter.fillRect(self.rect(), blue)
        super().paintEvent(event)


class GlassCard(QFrame):
    def __init__(self, *, strong: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GlassCardStrong" if strong else "GlassCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22 if strong else 18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(86, 111, 170, 34 if strong else 26))
        self.setGraphicsEffect(shadow)


class GlassDialog(QDialog):
    """Shared modal surface for confirmations and help content."""

    def __init__(
        self, title: str, parent: QWidget | None = None, *, minimum_size=(520, 280)
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowIcon(QIcon(str(ASSET_DIR / "app_icon.ico")))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setModal(True)
        self.setMinimumSize(*minimum_size)
        self.setObjectName("GlassDialog")
        self.setStyleSheet(
            "QDialog#GlassDialog{background:#EEF1FD;}"
            "QLabel#DialogTitle{font-size:20px;font-weight:700;color:#111323;}"
            "QLabel#DialogBody{font-size:14px;color:#606276;}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(14)
        header = QHBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("DialogTitle")
        header.addWidget(heading, 1)
        close = IconButton("close", tooltip="关闭")
        close.setFixedSize(38, 38)
        close.clicked.connect(self.reject)
        header.addWidget(close)
        root.addLayout(header)
        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(10)
        root.addLayout(self.body_layout, 1)
        self.action_layout = QHBoxLayout()
        self.action_layout.setSpacing(10)
        root.addLayout(self.action_layout)

    def add_action(self, text: str, *, primary: bool = False) -> QPushButton:
        action = QPushButton(text)
        action.setObjectName("PrimaryButton" if primary else "SecondaryButton")
        self.action_layout.addWidget(action)
        return action


class StatusChip(QLabel):
    def __init__(self, text: str = "等待", kind: str = "neutral", parent=None) -> None:
        super().__init__(text, parent)
        self.setObjectName("StatusChip")
        self.setProperty("kind", kind)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_status(self, text: str, kind: str) -> None:
        self.setText(text)
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)


class AgentIcon(QLabel):
    ICONS = {"hermes": "hermes", "claude": "claude", "codex": "codex"}

    def __init__(self, slot: str, parent=None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(46, 46)
        self.setPixmap(icon(self.ICONS.get(slot, "info")).pixmap(24, 24))
        self.setAccessibleName(f"{slot} agent")
        self.setStyleSheet(
            "background: rgba(255,255,255,205); border:1px solid rgba(255,255,255,225); "
            "border-radius:14px;"
        )


class StepItem(QWidget):
    def __init__(self, number: int, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("StepItem")
        self.number = QLabel(str(number))
        self.number.setObjectName("StepNumber")
        self.number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text = QLabel(text)
        self.text.setObjectName("StepText")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(14)
        layout.addWidget(self.number)
        layout.addWidget(self.text, 1)
        self.setFixedHeight(64)

    def set_active(self, active: bool) -> None:
        for widget in (self, self.number, self.text):
            widget.setProperty("active", active)
            widget.style().unpolish(widget)
            widget.style().polish(widget)


class StepRail(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("StepRail")
        self.setFixedWidth(238)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 20, 10, 18)
        layout.setSpacing(10)
        labels = ["录入 3 个 Bot Token", "激活私聊", "加入同一个群", "完成配置"]
        self.items = [StepItem(i + 1, label) for i, label in enumerate(labels)]
        for item in self.items:
            layout.addWidget(item)
        layout.addStretch(1)

        safety = QWidget()
        safety_layout = QVBoxLayout(safety)
        safety_layout.setContentsMargins(16, 14, 16, 10)
        title = QLabel("安全可靠")
        title.setObjectName("SafetyTitle")
        title_row = QHBoxLayout()
        title_icon = QLabel()
        title_icon.setPixmap(icon("shield").pixmap(17, 17))
        title_row.addWidget(title_icon)
        title_row.addWidget(title)
        title_row.addStretch(1)
        body = QLabel("所有数据仅存储在本地，\n由你完全掌控。")
        body.setObjectName("BodyText")
        body.setWordWrap(True)
        safety_layout.addLayout(title_row)
        safety_layout.addWidget(body)
        layout.addWidget(safety)
        self.set_active(0)

    def set_active(self, index: int) -> None:
        for position, item in enumerate(self.items):
            item.set_active(position == index)


class TitleBar(QWidget):
    refresh_requested = Signal()

    def __init__(self, window: QWidget, *, demo_mode: bool = False) -> None:
        super().__init__(window)
        self.host_window = window
        self._drag_origin = QPoint()
        self.setObjectName("TitleBar")
        self.setFixedHeight(72)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 10, 14, 10)
        layout.setSpacing(10)

        icon = QLabel()
        icon.setFixedSize(42, 42)
        pixmap = QPixmap(str(ASSET_DIR / "app_icon.png"))
        icon.setPixmap(
            pixmap.scaled(
                38,
                38,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        layout.addWidget(icon)
        title = QLabel("AI Agent Desktop" + ("  ·  预览模式" if demo_mode else ""))
        title.setObjectName("AppTitle")
        layout.addWidget(title)
        layout.addStretch(1)

        self.refresh = IconButton("refresh", tooltip="只读刷新全部状态")
        self.refresh.setObjectName("RefreshButton")
        self.refresh.clicked.connect(self.refresh_requested)
        layout.addWidget(self.refresh)
        minimize = IconButton("minimize", tooltip="最小化窗口")
        minimize.setObjectName("WindowButton")
        minimize.clicked.connect(window.showMinimized)
        layout.addWidget(minimize)
        self.maximize = IconButton("maximize", tooltip="最大化窗口")
        self.maximize.setObjectName("WindowButton")
        self.maximize.clicked.connect(self.toggle_maximized)
        layout.addWidget(self.maximize)
        close = IconButton("close", tooltip="关闭窗口")
        close.setObjectName("CloseButton")
        close.clicked.connect(window.close)
        layout.addWidget(close)
        self.close_button = close

    def toggle_maximized(self) -> None:
        if self.host_window.isMaximized():
            self.host_window.showNormal()
            self.maximize.setIcon(icon("maximize"))
            self.maximize.setToolTip("最大化窗口")
        else:
            self.host_window.showMaximized()
            self.maximize.setIcon(icon("restore"))
            self.maximize.setToolTip("还原窗口")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = (
                event.globalPosition().toPoint() - self.host_window.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and not self.host_window.isMaximized():
            self.host_window.move(event.globalPosition().toPoint() - self._drag_origin)
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()


class TelegramLauncher:
    OFFICIAL_DOWNLOAD = QUrl("https://desktop.telegram.org/")

    @staticmethod
    def native_url(https_url: str, *, group: bool = False) -> QUrl:
        parsed = urlparse(https_url)
        username = parsed.path.strip("/")
        query = parse_qs(parsed.query)
        payload_key = "startgroup" if group else "start"
        payload = query.get(payload_key) or query.get("start") or []
        params = {"domain": username}
        if payload:
            params[payload_key] = payload[0]
        return QUrl(f"tg://resolve?{urlencode(params)}")

    @classmethod
    def open_deep_link(cls, https_url: str, *, group: bool = False) -> bool:
        native = cls.native_url(https_url, group=group)
        if QDesktopServices.openUrl(native):
            return True
        return QDesktopServices.openUrl(QUrl(https_url))

    @classmethod
    def open_download(cls) -> bool:
        return QDesktopServices.openUrl(cls.OFFICIAL_DOWNLOAD)


class QrDialog(GlassDialog):
    def __init__(
        self,
        bot_name: str,
        username: str,
        deep_link: str,
        parent=None,
        *,
        expires_at: str | None = None,
    ) -> None:
        super().__init__("手机扫码激活", parent, minimum_size=(430, 520))
        qr_label = QLabel()
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_label.setPixmap(self._qr_pixmap(deep_link, 270))
        self.body_layout.addWidget(qr_label, 1)
        bot = QLabel(f"{bot_name}  ·  @{username}")
        bot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bot.setObjectName("CardTitle")
        self.body_layout.addWidget(bot)
        body = QLabel("用手机 Telegram 扫码，打开 Bot 私聊后点击 Start 即可完成激活。")
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setObjectName("DialogBody")
        self.body_layout.addWidget(body)
        self.expiry_label = QLabel("链接将在约 15 分钟后失效")
        self.expiry_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.expiry_label.setObjectName("SmallText")
        self.body_layout.addWidget(self.expiry_label)
        close = self.add_action("关闭", primary=True)
        close.clicked.connect(self.accept)
        self._expires_at = self._parse_expiry(expires_at)
        self._expiry_timer = QTimer(self)
        self._expiry_timer.setInterval(1000)
        self._expiry_timer.timeout.connect(self._update_expiry)
        if self._expires_at is not None:
            self._expiry_timer.start()
            self._update_expiry()

    @staticmethod
    def _parse_expiry(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    def _update_expiry(self) -> None:
        if self._expires_at is None:
            return
        remaining = int((self._expires_at - datetime.now(UTC)).total_seconds())
        if remaining <= 0:
            self.expiry_label.setText("链接已过期，请返回页面刷新后重新打开")
            self.expiry_label.setProperty("kind", "error")
            self.expiry_label.style().unpolish(self.expiry_label)
            self.expiry_label.style().polish(self.expiry_label)
            self._expiry_timer.stop()
            return
        minutes, seconds = divmod(remaining, 60)
        self.expiry_label.setText(f"链接将在 {minutes:02d}:{seconds:02d} 后失效")

    def closeEvent(self, event) -> None:
        self._expiry_timer.stop()
        super().closeEvent(event)

    @staticmethod
    def _qr_pixmap(value: str, size: int) -> QPixmap:
        import qrcode

        qr = qrcode.QRCode(version=None, box_size=8, border=3)
        qr.add_data(value)
        qr.make(fit=True)
        image = qr.make_image(fill_color="#181B38", back_color="#F8FAFF")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        pixmap = QPixmap()
        # PySide6 6.7 accepts the format name as str at runtime, while its
        # bundled type stub only declares a bytes-like value.
        format_name: Any = "PNG"
        pixmap.loadFromData(buffer.getvalue(), format_name)
        return pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )


class TaskSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str, str)


class ApiTask(QRunnable):
    def __init__(self, function) -> None:
        super().__init__()
        self.function = function
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            result = self.function()
        except Exception as exc:
            code = getattr(exc, "code", "GUI_API_ERROR")
            self.signals.failed.emit(str(exc), str(code))
        else:
            self.signals.succeeded.emit(result)


class _CallbackReceiver(QObject):
    def __init__(self, runner: ApiRunner, on_success, on_error) -> None:
        super().__init__()
        self.runner = runner
        self.on_success = on_success
        self.on_error = on_error

    @Slot(object)
    def success(self, result) -> None:
        self.on_success(result)
        self.runner._release(self)

    @Slot(str, str)
    def error(self, message: str, code: str) -> None:
        self.on_error(message, code)
        self.runner._release(self)


class ApiRunner:
    def __init__(self) -> None:
        self.pool = QThreadPool.globalInstance()
        self._active: set[_CallbackReceiver] = set()

    def run(self, function, on_success, on_error) -> ApiTask:
        task = ApiTask(function)
        receiver = _CallbackReceiver(self, on_success, on_error)
        self._active.add(receiver)
        task.signals.succeeded.connect(receiver.success)
        task.signals.failed.connect(receiver.error)
        self.pool.start(task)
        return task

    def _release(self, receiver: _CallbackReceiver) -> None:
        self._active.discard(receiver)
        receiver.deleteLater()


class RefreshSpinner:
    def __init__(self, button: QPushButton) -> None:
        self.button = button
        self.timer = QTimer(button)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        self.button.setProperty("loading", True)
        self.button.style().unpolish(self.button)
        self.button.style().polish(self.button)

    def start(self) -> None:
        self.button.setEnabled(False)
        self.button.setProperty("loading", True)
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()
        self.button.setProperty("loading", False)
        self.button.setIcon(icon("refresh"))
        self.button.setEnabled(True)

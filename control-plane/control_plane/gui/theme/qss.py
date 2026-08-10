from __future__ import annotations


def build_stylesheet() -> str:
    return """
    * {
        font-family: "Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI";
        color: #111323;
        outline: none;
    }
    QWidget#GradientCanvas { background: transparent; }
    QWidget#TitleBar {
        background: rgba(255, 255, 255, 82);
        border-bottom: 1px solid rgba(255, 255, 255, 150);
    }
    QLabel#AppTitle { font-size: 18px; font-weight: 650; }
    QPushButton#WindowButton, QPushButton#RefreshButton {
        border: none;
        background: transparent;
        font-size: 18px;
        min-width: 48px;
        min-height: 46px;
        border-radius: 11px;
    }
    QPushButton#RefreshButton {
        background: rgba(255, 255, 255, 145);
        border: 1px solid rgba(255, 255, 255, 180);
    }
    QPushButton#WindowButton:hover, QPushButton#RefreshButton:hover {
        background: rgba(255, 255, 255, 170);
    }
    QPushButton#CloseButton:hover { background: rgba(231, 92, 105, 190); color: white; }

    QFrame#GlassCard, QWidget#GlassCard {
        background: rgba(255, 255, 255, 118);
        border: 1px solid rgba(255, 255, 255, 180);
        border-radius: 17px;
    }
    QFrame#GlassCardStrong, QWidget#GlassCardStrong {
        background: rgba(255, 255, 255, 151);
        border: 1px solid rgba(255, 255, 255, 205);
        border-radius: 17px;
    }
    QFrame#StepRail {
        background: rgba(255, 255, 255, 88);
        border: 1px solid rgba(255, 255, 255, 150);
        border-radius: 17px;
    }
    QWidget#StepItem {
        background: transparent;
        border: 1px solid transparent;
        border-radius: 11px;
    }
    QWidget#StepItem[active="true"] {
        background: rgba(92, 104, 244, 18);
        border: 1px solid rgba(89, 101, 220, 42);
    }
    QLabel#StepNumber {
        background: rgba(255, 255, 255, 185);
        border: 1px solid rgba(194, 207, 235, 160);
        border-radius: 15px;
        min-width: 30px;
        max-width: 30px;
        min-height: 30px;
        max-height: 30px;
        font-size: 15px;
        font-weight: 650;
    }
    QLabel#StepNumber[active="true"] {
        color: white;
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #4F83FA,stop:1 #6269EC);
        border: none;
    }
    QLabel#StepText { font-size: 15px; color: #45485A; }
    QLabel#StepText[active="true"] { color: #376DE2; font-weight: 650; }
    QLabel#PageTitle { font-size: 38px; font-weight: 700; color: #0E101D; }
    QLabel#WelcomeTitle { font-size: 42px; font-weight: 730; color: #0E101D; }
    QLabel#Subtitle { font-size: 15px; color: #626477; }
    QLabel#CardTitle { font-size: 18px; font-weight: 650; }
    QLabel#BodyText { font-size: 14px; color: #626477; }
    QLabel#SmallText { font-size: 12px; color: #85879A; }
    QLabel#SafetyTitle { font-size: 13px; font-weight: 650; }
    QLabel#StatusChip {
        border-radius: 11px;
        padding: 4px 10px;
        font-size: 12px;
        font-weight: 600;
    }
    QLabel#StatusChip[kind="success"] { color: #278D4B; background: rgba(221, 247, 231, 220); }
    QLabel#StatusChip[kind="warning"] { color: #B66B09; background: rgba(255, 245, 217, 225); }
    QLabel#StatusChip[kind="neutral"] { color: #5D6275; background: rgba(239, 243, 252, 220); }

    QPushButton#PrimaryButton {
        color: white;
        min-height: 50px;
        border-radius: 11px;
        border: 1px solid rgba(255, 255, 255, 80);
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #4582F9,stop:.58 #5C6EF1,stop:1 #8B5CF6);
        font-size: 16px;
        font-weight: 650;
        padding: 0 24px;
    }
    QPushButton#PrimaryButton:hover {
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #3978F3,stop:.58 #5365EA,stop:1 #8051EC);
    }
    QPushButton#PrimaryButton:disabled { background: rgba(107, 119, 170, 95); color: rgba(255,255,255,170); }
    QPushButton#SecondaryButton, QPushButton#InlineButton {
        background: rgba(255, 255, 255, 180);
        border: 1px solid rgba(255, 255, 255, 210);
        border-radius: 10px;
        min-height: 48px;
        font-size: 15px;
        font-weight: 600;
        padding: 0 20px;
    }
    QPushButton#InlineButton { min-height: 42px; padding: 0 15px; }
    QPushButton#SecondaryButton:hover, QPushButton#InlineButton:hover { background: rgba(255, 255, 255, 225); }
    QPushButton#TelegramButton {
        color: white;
        min-height: 48px;
        border-radius: 10px;
        border: 1px solid rgba(255, 255, 255, 85);
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #398DF4,stop:1 #775DEF);
        font-size: 15px;
        font-weight: 600;
        padding: 0 17px;
    }
    QPushButton#QrButton {
        background: rgba(255, 255, 255, 176);
        border: 1px solid rgba(255, 255, 255, 210);
        border-radius: 10px;
        min-width: 54px;
        max-width: 54px;
        min-height: 48px;
        font-size: 20px;
    }
    QLineEdit#TokenInput {
        min-height: 44px;
        background: rgba(255, 255, 255, 205);
        border: 1px solid rgba(200, 221, 245, 160);
        border-radius: 10px;
        padding: 0 14px;
        font-size: 15px;
        selection-background-color: #6B72EA;
    }
    QLineEdit#TokenInput:focus { border: 1px solid rgba(83, 117, 235, 180); }
    QFrame#BotRow { border: none; border-bottom: 1px solid rgba(205, 216, 238, 105); }
    QFrame#FooterBar { background: transparent; border: none; }
    QFrame#SuccessBanner {
        background: rgba(229, 248, 238, 220);
        border: 1px solid rgba(152, 220, 180, 100);
        border-radius: 10px;
    }
    QScrollArea { background: transparent; border: none; }
    QScrollBar:vertical { width: 8px; background: transparent; }
    QScrollBar::handle:vertical { background: rgba(101, 111, 164, 70); border-radius: 4px; min-height: 28px; }
    """

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QFontDatabase, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QSizePolicy
from .icons import icon

assets = Path(__file__).resolve().parents[1] / "brand"
NAVY, HIGH, WHITE, AMBER = "#080F16", "#182D42", "#E1E1E1", "#E0A458"


def apply_theme(app):
    for path in assets.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Nunito Sans Normal", 11))
    app.setStyleSheet("""
        QWidget { color:#E1E1E1; font-family:'Nunito Sans Normal','Nunito Sans'; font-size:16px; }
        QMainWindow, QDialog, QWidget#page { background:#101E2B; }
        QWidget#page {background:qradialgradient(cx:0.90,cy:0.06,radius:1.2,fx:0.90,fy:0.06,stop:0 #182D42,stop:1 #080F16);}
        QFrame#rail {background:#0B151F; border-right:1px solid #304353;}
        QFrame#stage {background:qradialgradient(cx:0.5,cy:0.08,radius:1.2,fx:0.5,fy:0.08,stop:0 #1A2F43,stop:1 #101E2B); border:1px solid #354B5B; border-radius:12px;}
        QFrame#rows {background:#111F2C; border:1px solid #374B5A; border-radius:11px;}
        QFrame#rule {background:#344858;max-height:1px;min-height:1px;}
        QLabel {background:transparent;}
        QPushButton, QToolButton, QComboBox, QSpinBox, QDoubleSpinBox {
          background:#182B3C; border:1px solid #486071; border-radius:7px; padding:7px 12px; color:#E1E1E1;}
        QPushButton:hover, QToolButton:hover, QComboBox:hover {background:#264054;}
        QPushButton:pressed, QPushButton:checked, QToolButton:checked {background:#2D4254; border-color:#8599A8;}
        QPushButton:disabled, QToolButton:disabled, QComboBox:disabled {color:#8B9AA5; background:#13202B; border-color:#30404B;}
        QPushButton#primary {background:#E0A458;color:#080F16;font-weight:bold;border-color:#E0A458;}
        QPushButton#primary:hover {background:#EDB673;}
        QPushButton#transport {background:#E1E1E1;color:#080F16;border-radius:26px;padding:0;}
        QPushButton#step {border-radius:21px;padding:0;}
        QPushButton#nav {text-align:left; padding:10px 13px; border:1px solid transparent; background:transparent;}
        QPushButton#nav:checked, QPushButton#nav:hover {background:#182D40;}
        QPushButton#quiet {background:transparent;border:1px solid transparent;}
        QPushButton#quiet:hover {background:#203447;}
        QPushButton:focus, QPushButton#quiet:focus, QPushButton#primary:focus, QPushButton#nav:focus, QToolButton:focus, QComboBox:focus,
        QLineEdit:focus, QPlainTextEdit:focus, QSlider:focus, QTableWidget:focus {border:2px solid #D6E4EB;}
        QLineEdit,QPlainTextEdit,QListWidget,QTableWidget {background:#0E1C28;border:1px solid #405766;border-radius:6px;padding:6px;selection-background-color:#395773;}
        QTextEdit, QTableView, QAbstractItemView, QHeaderView::section, QMenu, QMenuBar, QToolTip {background:#152636;color:#E1E1E1;}
        QMenu {padding:5px;border:1px solid #4B6273;} QMenu::item {padding:7px 18px;} QMenu::item:selected {background:#36546B;}
        QComboBox QAbstractItemView {background:#152636;selection-background-color:#36546B;}
        QHeaderView::section {padding:5px;border:1px solid #314451;}
        QSlider::groove:horizontal {height:5px;background:#344652;border-radius:2px;}
        QSlider::sub-page:horizontal {background:#A9B8C3;border-radius:2px;}
        QSlider::handle:horizontal {width:15px;background:#E1E1E1;margin:-5px 0;border-radius:7px;}
        QScrollArea {background:transparent;border:0;} QScrollArea > QWidget > QWidget {background:transparent;}
        QScrollBar:vertical {width:10px;background:#102030;} QScrollBar::handle:vertical {background:#536879;border-radius:4px;min-height:22px;}
        QCheckBox,QRadioButton {padding:4px;} QCheckBox::indicator, QRadioButton::indicator {width:17px;height:17px;}
        QProgressBar {background:#152636;border:1px solid #425666;border-radius:5px;text-align:center;}
        QProgressBar::chunk {background:#456579;}
    """)


def label(text="", size=16, kind="body", muted=False, weight=500):
    w = QLabel()
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setText(text)
    family = {"body": "Nunito Sans Normal", "head": "Nunito", "he": "Rubik"}[kind]
    w.setStyleSheet(
        f"font-family:'{family}';font-size:{size}px;font-weight:{weight};color:{'#B1BDC7' if muted else WHITE};"
    )
    w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    return w


def button(text, action=None, name=None, description=None, icon_name=None):
    w = QPushButton(text)
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    w.setMinimumHeight(42)
    if name:
        w.setObjectName(name)
    if icon_name:
        w.setIcon(icon(icon_name, NAVY if name in ("primary", "transport") else WHITE))
        w.setIconSize(QSize(20, 20))
    if description:
        w.setAccessibleName(description)
        w.setToolTip(description)
    if action is not None:
        w.clicked.connect(lambda checked=False: action())
    return w


def rule():
    w = QFrame()
    w.setObjectName("rule")
    w.setFixedHeight(1)
    return w


def picture(file, width, height, crop=False, anchor=0.5):
    w = QLabel()
    w.setFixedSize(width, height)
    w.setAccessibleName("")
    im = QPixmap(str(assets / file))
    if not im.isNull():
        scale = w.devicePixelRatioF()
        size = QSize(round(width * scale), round(height * scale))
        im = im.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding if crop else Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if crop:
            im = im.copy(
                (im.width() - size.width()) // 2,
                round((im.height() - size.height()) * anchor),
                size.width(),
                size.height(),
            )
        im.setDevicePixelRatio(scale)
        w.setPixmap(im)
    w.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return w

"""Light desktop design system and compact native navigation controls."""

from functools import lru_cache

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

ACCENT = "#d32342"
STYLE = """
QWidget {background: transparent; color: #202023; font-family: 'Segoe UI'; font-size: 13px;}
QMainWindow, QDialog, QStackedWidget {background: white;}
QWidget#sidebar {background: #f7f7f9; border-right: 1px solid #e9e9ed;}
QLabel#brand {color: #d32342; font-size: 30px; font-weight: 700;}
QLabel#eyebrow {color: #767680; font-size: 10px; font-weight: 600;}
QLabel#pageTitle {font-size: 36px; font-weight: 700;}
QLabel#movieTitle {font-size: 24px; font-weight: 600;}
QLabel#muted, QLabel#pageSubtitle {color: #767680;}
QLabel#identifier {color: #d32342; font-size: 12px; font-weight: 600;}
QLabel#cardTitle {font-size: 15px; font-weight: 600;}
QGroupBox {background: #fafafa; border: 1px solid #e9e9ed; border-radius: 14px;
    margin-top: 16px; padding: 22px 18px 18px;}
QGroupBox::title {subcontrol-origin: margin; left: 18px; padding: 0 6px;
    color: #202023; font-size: 17px; font-weight: 600;}
QPushButton {background: #f3f3f5; border: 1px solid transparent; border-radius: 9px;
    padding: 9px 12px; font-weight: 500;}
QPushButton:hover {background: #eaeaec;}
QPushButton:focus {border: 1px solid #d32342;}
QPushButton:disabled {color: #b4b4bd; background: #f7f7f8;}
QPushButton[primary="true"] {background: #d32342; color: white;}
QPushButton[primary="true"]:hover {background: #b91c37;}
QPushButton[primary="true"]:disabled {background: #f3dce1; color: #ae6f7c;}
QPushButton#nav {text-align: left; padding: 13px 12px; background: transparent;}
QPushButton#nav:hover {background: #eeeeF1;}
QPushButton#nav:focus {border: 1px solid #d0d0d5;}
QPushButton#nav:checked {background: #fdecef; color: #bb1b36; font-weight: 600;}
QFrame#segment {background: #f2f2f5; border-radius: 9px;}
QPushButton#view {padding: 7px 10px; background: transparent; color: #767680; border-radius: 7px;}
QPushButton#view:checked {background: white; color: #202023; border: 1px solid #e6e6ea;}
QPushButton#pageNumber {padding: 6px 0; min-width: 24px;
    background: transparent; border-radius: 8px;}
QPushButton#pageNumber:checked {background: #d32342; color: white;}
QLineEdit, QTextEdit {background: #f7f7f9; border: 1px solid #e6e6ea; border-radius: 10px;
    padding: 10px 12px; selection-background-color: #fdecef; selection-color: #bb1b36;}
QLineEdit:focus, QTextEdit:focus {border: 1px solid #d8798b; background: white;}
QComboBox {background: #f7f7f9; border: 1px solid #e6e6ea; border-radius: 9px; padding: 8px 12px;}
QComboBox::drop-down {border: none; width: 24px;}
QComboBox QAbstractItemView {background: white; selection-background-color: #fdecef;
    selection-color: #202023; border: 1px solid #e6e6ea;}
QScrollArea, QTableWidget {border: none; background: white;}
QTableWidget {alternate-background-color: #fafafa; gridline-color: #eeeeF1;
    selection-background-color: #fdecef; selection-color: #202023;}
QTableWidget::item {padding: 7px; border-bottom: 1px solid #eeeeF1;}
QHeaderView::section {background: white; color: #767680; font-size: 11px; font-weight: 600;
    padding: 11px 7px; border: none; border-bottom: 1px solid #e9e9ed;}
QFrame#movieCard {background: white; border: none;}
QScrollBar:vertical {background: transparent; width: 8px; margin: 4px 0;}
QScrollBar::handle:vertical {background: #cfcfd6; border-radius: 4px; min-height: 25px;}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {height: 0;}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {background: transparent;}
QScrollBar:horizontal {background: #f7f7f9; height: 8px;}
QScrollBar::handle:horizontal {background: #cfcfd6; border-radius: 4px; min-width: 25px;}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {width: 0;}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {background: transparent;}
QSplitter::handle {background: #e9e9ed;}
QStatusBar {background: white; color: #767680; border-top: 1px solid #eeeeF1;}
QToolTip {background: #202023; color: white; border: none; padding: 7px;}
"""

ICON_PATHS = {
    "library": '<rect x="3" y="3" width="7" height="7" rx="1.3"/>'
    '<rect x="14" y="3" width="7" height="7" rx="1.3"/>'
    '<rect x="3" y="14" width="7" height="7" rx="1.3"/>'
    '<rect x="14" y="14" width="7" height="7" rx="1.3"/>',
    "auth": '<rect x="5" y="10" width="14" height="11" rx="2"/>'
    '<path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    "download": '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
    "folder": '<path d="M3 6h7l2 3h9v11H3z"/>',
    "table": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M3 14h18M9 4v16"/>',
}


@lru_cache(maxsize=24)
def line_icon(name, color="#707079"):
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.7" stroke-linecap="round" '
        f'stroke-linejoin="round">{ICON_PATHS[name]}</svg>'
    )
    pixmap = QPixmap(96, 96)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(svg.encode()).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(4)
    return QIcon(pixmap)


class Navigation(QFrame):
    currentRowChanged = Signal(int)

    def __init__(self, names, parent=None):
        super().__init__(parent)
        self.row = -1
        self.buttons = []
        self.group = QButtonGroup(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.icons = ["library", "auth", "search", "download", "folder"]
        for index, name in enumerate(names):
            if index in (0, 1):
                if index:
                    layout.addSpacing(20)
                heading = QLabel("COLLECTION" if index == 0 else "WORKSPACE")
                heading.setObjectName("eyebrow")
                layout.addWidget(heading)
            control = QPushButton(name.replace("&", "&&"))
            control.setObjectName("nav")
            control.setCheckable(True)
            control.setCursor(Qt.CursorShape.PointingHandCursor)
            control.setIcon(line_icon(self.icons[index]))
            control.setIconSize(QSize(18, 18))
            self.group.addButton(control, index)
            self.buttons.append(control)
            layout.addWidget(control)
        self.group.idClicked.connect(self.setCurrentRow)

    def currentRow(self):
        return self.row

    def setCurrentRow(self, index):
        if not 0 <= index < len(self.buttons) or index == self.row:
            return
        self.row = index
        for row, control in enumerate(self.buttons):
            control.setChecked(row == index)
            control.setIcon(line_icon(self.icons[row], ACCENT if row == index else "#707079"))
        self.currentRowChanged.emit(index)


class ViewSelector(QFrame):
    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("segment")
        self.index = 0
        self.group = QButtonGroup(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        for index, name, glyph in [(1, "Cover view", "library"), (0, "Table view", "table")]:
            control = QPushButton(name)
            control.setObjectName("view")
            control.setCheckable(True)
            control.setChecked(index == self.index)
            control.setIcon(line_icon(glyph))
            control.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(control, index)
            layout.addWidget(control)
        self.group.idClicked.connect(self.setCurrentIndex)

    def currentIndex(self):
        return self.index

    def setCurrentIndex(self, index):
        if index not in (0, 1) or index == self.index:
            return
        self.index = index
        self.group.button(index).setChecked(True)
        self.currentIndexChanged.emit(index)

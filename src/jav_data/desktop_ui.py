"""Native desktop screens backed by the existing local application services."""

import json
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from html import escape
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QIntValidator,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPixmap,
    QShortcut,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from jav_data.desktop_theme import ACCENT, STYLE, Navigation, ViewSelector, line_icon
from jav_data.library import FIELD_LABELS, TAG_LABELS

NAVIGATION = [
    "Library",
    "Website Authentication",
    "Search Product URLs",
    "Scraping & Downloads",
    "Database & Library",
]


class FittedCover(QWidget):
    """Contain the original image without exceeding its physical pixel resolution."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.original = QPixmap()
        self.setMinimumSize(80, 80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self):
        return QSize(600, 350)

    def setPixmap(self, pixmap):
        self.original = pixmap
        self.update()

    def image_rect(self):
        if self.original.isNull():
            return QRectF()
        area = self.contentsRect()
        width, height = self.original.width(), self.original.height()
        scale = min(area.width() / width, area.height() / height, 1 / self.devicePixelRatioF())
        return QRectF(
            area.x() + (area.width() - width * scale) / 2,
            area.y() + (area.height() - height * scale) / 2,
            width * scale,
            height * scale,
        )

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.contentsRect()), 11, 11)
        painter.setClipPath(clip)
        painter.fillRect(self.contentsRect(), QColor("#f5f3f2"))
        if not self.original.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(self.image_rect(), self.original, QRectF(self.original.rect()))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.image_rect().contains(
            event.position()
        ):
            self.clicked.emit()
        super().mousePressEvent(event)


class CardText(QLabel):
    """Bound long titles/cast lists while retaining the full text in a tooltip."""

    def __init__(self, text, lines=1, parent=None):
        super().__init__(parent)
        self.full_text = text or "—"
        self.lines = lines
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(lines > 1)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setToolTip(self.full_text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.fontMetrics().lineSpacing() * lines + 8)
        self.update_text()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_text()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange and hasattr(self, "full_text"):
            self.setFixedHeight(self.fontMetrics().lineSpacing() * self.lines + 8)
            self.update_text()

    def update_text(self):
        width = max(1, self.contentsRect().width())
        text_layout = QTextLayout(self.full_text, self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        text_layout.setTextOption(option)
        text_layout.beginLayout()
        lines = []
        for index in range(self.lines):
            line = text_layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            remaining = self.full_text[line.textStart() :]
            if index == self.lines - 1:
                lines.append(
                    self.fontMetrics().elidedText(remaining, Qt.TextElideMode.ElideRight, width)
                )
            else:
                lines.append(remaining[: line.textLength()].strip())
        text_layout.endLayout()
        self.setText("\n".join(lines))


class MovieCard(QFrame):
    WIDTH = 294
    HEIGHT = 360

    def __init__(self, movie, open_movie, parent=None):
        super().__init__(parent)
        self.open_movie = open_movie
        self.setObjectName("movieCard")
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(6)
        self.cover = FittedCover()
        self.cover.setFixedHeight(196)
        self.cover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cover.setToolTip("Open movie details")
        self.cover.clicked.connect(open_movie)
        layout.addWidget(self.cover)
        identifier = CardText(movie["distribution_product_id"])
        identifier.setObjectName("identifier")
        date = CardText(movie["streaming_release_date"])
        date.setObjectName("muted")
        date.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        metadata = QHBoxLayout()
        metadata.addWidget(identifier, 1)
        metadata.addWidget(date, 1)
        layout.addLayout(metadata)
        title = CardText(movie["title"], lines=3)
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        cast = CardText(" · ".join(movie["actresses"]), lines=2)
        cast.setObjectName("muted")
        layout.addWidget(cast)
        layout.addStretch()

    def set_cover(self, pixmap):
        self.cover.setPixmap(pixmap)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_movie()
        super().mouseDoubleClickEvent(event)


class CardGrid(QWidget):
    GAP = 22

    def __init__(self):
        super().__init__()
        self.cards = []
        self.columns = 0
        self.grid = QGridLayout(self)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid.setSpacing(self.GAP)
        self.grid.setContentsMargins(0, 0, 8, 0)

    def minimumSizeHint(self):
        rows = (len(self.cards) + max(1, self.columns) - 1) // max(1, self.columns)
        height = rows * MovieCard.HEIGHT + max(0, rows - 1) * self.GAP
        return QSize(MovieCard.WIDTH, height)

    def set_cards(self, cards):
        while self.grid.count():
            item = self.grid.takeAt(0)
            item.widget().hide()
            item.widget().deleteLater()
        self.cards = cards
        self.reflow(force=True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def reflow(self, force=False):
        columns = max(1, (self.width() - 8 + self.GAP) // (MovieCard.WIDTH + self.GAP))
        if columns == self.columns and not force:
            return
        for column in range(self.columns):
            self.grid.setColumnStretch(column, 0)
        self.columns = columns
        for index, card in enumerate(self.cards):
            self.grid.removeWidget(card)
            self.grid.addWidget(card, index // columns, index % columns)
            card.show()
        self.updateGeometry()


class MovieDetailDialog(QDialog):
    """Keep the centered cover area near sixty percent of the window height."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_cover_area()

    def fit_cover_area(self):
        if getattr(self, "cover_widget", None) is not None:
            self.cover_widget.setFixedHeight(max(80, int(self.height() * 0.60)))


class ApiClient(QObject):
    finished = Signal(object, object, object, object)

    def __init__(self, base, parent=None):
        super().__init__(parent)
        self.base = base
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="desktop-api")
        self.preview_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="desktop-preview")
        self.finished.connect(self.deliver)
        self.error_handler = None
        self.groups = {}
        self.group_versions = {}
        self.pending_paths = set()

    def request(self, path, body=None, raw=False):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        try:
            with urlopen(req, timeout=65) as response:
                content = response.read()
                return content if raw else json.loads(content)
        except HTTPError as error:
            detail = json.loads(error.read()).get("detail", "Request failed")
            raise ValueError(detail if isinstance(detail, str) else "Invalid request") from error

    def cancel_group(self, group):
        self.group_versions[group] = self.group_versions.get(group, 0) + 1
        for future in list(self.groups.get(group, ())):
            future.cancel()

    def submit(
        self, path, callback=None, body=None, raw=False, group=None, once=False, on_error=None
    ):
        if once and path in self.pending_paths:
            return
        if once:
            self.pending_paths.add(path)
        version = self.group_versions.get(group, 0)
        pool = self.preview_pool if group == "library" and raw else self.pool
        future = pool.submit(self.request, path, body, raw)
        if group:
            self.groups.setdefault(group, set()).add(future)

        def completed(task):
            if once:
                self.pending_paths.discard(path)
            if group:
                self.groups[group].discard(task)
                if task.cancelled() or self.group_versions.get(group, 0) != version:
                    return
            try:
                result, error = task.result(), None
            except Exception as failure:
                result, error = None, str(failure)
            try:
                self.finished.emit(callback, result, error, (group, version, on_error))
            except RuntimeError:
                pass

        future.add_done_callback(completed)

    def deliver(self, callback, result, error, token):
        group, version, on_error = token
        if group and self.group_versions.get(group, 0) != version:
            return
        if getattr(self.parent(), "closing", False):
            return
        if error:
            handler = on_error or self.error_handler
            if handler:
                handler(error)
        elif callback:
            callback(result)


def button(label, callback, primary=False):
    widget = QPushButton(label.replace("&", "&&"))
    widget.setProperty("primary", primary)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(lambda _checked=False: callback())
    return widget


def page(title):
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(28, 24, 28, 18)
    layout.setSpacing(16)
    heading = QLabel(title)
    heading.setObjectName("pageTitle")
    heading.setWordWrap(True)
    layout.addWidget(heading)
    subtitle = QLabel(
        {
            "Library": "Your collection, in one place.",
            "Website Authentication": "Your browser session, on this device.",
            "Search Product URLs": "Find products by name, ID or keyword.",
            "Scraping & Downloads": "From product URLs to your collection.",
            "Database & Library": "One database. All your collections.",
        }[title]
    )
    subtitle.setObjectName("pageSubtitle")
    subtitle.setWordWrap(True)
    layout.addWidget(subtitle)
    return widget, layout


def table(columns):
    widget = QTableWidget(0, len(columns))
    widget.setHorizontalHeaderLabels(columns)
    widget.setAlternatingRowColors(True)
    widget.setShowGrid(False)
    widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    widget.verticalHeader().hide()
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
    return widget


class DesktopWindow(QMainWindow):
    def __init__(self, backend, controller, settings):
        super().__init__()
        self.backend, self.controller, self.settings = backend, controller, settings
        self.api = ApiClient(backend.base, self)
        self.api.error_handler = self.show_error
        self.closing = False
        self.library_page = self.search_page = 1
        self.library_pages = 1
        self.library_generation = 0
        self.library_sort_column = 4
        self.library_sort_order = "asc"
        self.library_tag_filter = None
        self.search_id = None
        self.search_running = False
        self.dialogs = []
        self.movie_dialog = None
        self.movie_content = None
        self.movie_request_generation = 0
        self.movie_view_generation = 0
        self.setWindowTitle("jav-data · Portable desktop scraper")
        self.resize(1440, 960)
        self.setMinimumSize(900, 650)
        self.setStyleSheet(STYLE)
        splitter = QSplitter()
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(16, 28, 16, 20)
        side_layout.setSpacing(10)
        brand = QLabel("Data+")
        brand.setObjectName("brand")
        side_layout.addWidget(brand)
        side_layout.addSpacing(24)
        self.navigation = Navigation(NAVIGATION)
        side_layout.addWidget(self.navigation)
        side_layout.addStretch()
        libraries_heading = QLabel("LOCAL LIBRARIES")
        libraries_heading.setObjectName("eyebrow")
        side_layout.addWidget(libraries_heading)
        self.sidebar_libraries = QLabel()
        self.sidebar_libraries.setTextFormat(Qt.TextFormat.PlainText)
        self.sidebar_libraries.setObjectName("muted")
        self.sidebar_libraries.setWordWrap(True)
        side_layout.addWidget(self.sidebar_libraries)
        side_layout.addSpacing(18)
        footer = QLabel("jav-data · Local collection")
        footer.setObjectName("muted")
        side_layout.addWidget(footer)
        sidebar.setMinimumWidth(216)
        sidebar.setMaximumWidth(260)
        self.stack = QStackedWidget()
        splitter.addWidget(sidebar)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        self.build_library()
        self.build_authentication()
        self.build_search()
        self.build_scraping()
        self.build_storage()
        self.navigation.currentRowChanged.connect(self.change_page)
        self.controller.pageShown.connect(self.show_browser_page)
        self.controller.pageClosed.connect(self.browser_page_closed)
        self.navigation.setCurrentRow(0)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_status)
        self.refresh_timer.start(2500)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.load_search)
        self.api.submit("/api/product-folders", self.show_folders)
        self.statusBar().showMessage("Ready")

    def show_error(self, error):
        if not self.closing:
            self.statusBar().showMessage(str(error), 15000)
            if hasattr(self, "auth_feedback"):
                self.auth_feedback.setText(str(error))
                for control in self.auth_buttons:
                    control.setEnabled(True)
            if self.search_running:
                self.search_running = False
                self.search_button.setEnabled(True)
                self.search_feedback.setText(str(error))

    def change_page(self, index):
        self.stack.setCurrentIndex(index)
        if index == 0:
            self.load_library()
        if index == 3:
            self.refresh_status()

    def search_row(self, callback):
        layout = QHBoxLayout()
        text = QLineEdit()
        text.setPlaceholderText("Title, distribution ID, actress, maker or other keyword")
        action = button("Search", callback, primary=True)
        text.addAction(line_icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        text.returnPressed.connect(callback)
        layout.addWidget(text, 1)
        layout.addWidget(action)
        return layout, text, action

    def build_library(self):
        widget, layout = page("Library")
        heading = layout.takeAt(0).widget()
        subtitle = layout.takeAt(0).widget()
        titles = QVBoxLayout()
        titles.setSpacing(5)
        titles.addWidget(heading)
        titles.addWidget(subtitle)
        header_row = QHBoxLayout()
        header_row.addLayout(titles, 1)
        row, self.library_query, search_action = self.search_row(self.search_library)
        search_action.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.library_query.setPlaceholderText("Search your library")
        self.library_query.setToolTip("Title, product ID, actress, maker or other keyword")
        self.library_query.setMinimumWidth(180)
        self.library_query.setMaximumWidth(360)
        header_row.addLayout(row)
        layout.addLayout(header_row)
        self.library_filter_controls = QWidget()
        filters = QHBoxLayout(self.library_filter_controls)
        filters.setContentsMargins(0, 0, 0, 0)
        self.library_filter_label = QLabel()
        self.library_filter_label.setTextFormat(Qt.TextFormat.PlainText)
        self.library_filter_label.setWordWrap(True)
        filters.addWidget(self.library_filter_label, 1)
        self.clear_library_filter_button = button("Clear filter", self.clear_library_filter)
        filters.addWidget(self.clear_library_filter_button)
        layout.addWidget(self.library_filter_controls)
        self.library_filter_controls.hide()
        toolbar = QHBoxLayout()
        self.library_count = QLabel()
        self.library_count.setObjectName("muted")
        toolbar.addWidget(self.library_count)
        toolbar.addStretch()
        self.library_sort_label = QLabel("Sort by")
        self.library_sort_label.setObjectName("muted")
        toolbar.addWidget(self.library_sort_label)
        self.library_sort_combo = QComboBox()
        for name, column in [
            ("Title", 4),
            ("Release date", 1),
            ("Product ID", 2),
            ("Actresses", 3),
            ("Maker", 5),
        ]:
            self.library_sort_combo.addItem(name, column)
        self.library_sort_combo.activated.connect(self.choose_library_sort)
        toolbar.addWidget(self.library_sort_combo)
        self.library_order_button = button("↑", self.reverse_library_sort)
        self.library_order_button.setToolTip("Ascending; click to reverse")
        self.library_order_button.setAccessibleName("Reverse library sort order")
        self.library_order_button.setFixedWidth(38)
        toolbar.addWidget(self.library_order_button)
        toolbar.addSpacing(8)
        self.library_view = ViewSelector()
        self.library_view.currentIndexChanged.connect(self.change_library_view)
        toolbar.addWidget(self.library_view)
        layout.addLayout(toolbar)
        self.library_table = table(
            ["Cover", "Release date", "Product ID", "Actresses", "Title", "Maker"]
        )
        header = self.library_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setSectionsMovable(True)
        header.setFirstSectionMovable(True)
        for column, width in enumerate([130, 135, 140, 180, 360, 160]):
            header.resizeSection(column, width)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(4, Qt.SortOrder.AscendingOrder)
        header.sectionClicked.connect(self.sort_library)
        self.library_table.cellDoubleClicked.connect(lambda row, _col: self.open_movie(row))
        self.library_views = QStackedWidget()
        self.library_views.addWidget(self.library_table)
        self.card_grid = CardGrid()
        self.card_scroll = QScrollArea()
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.card_scroll.setWidget(self.card_grid)
        self.library_views.addWidget(self.card_scroll)
        self.library_cards = {}
        self.library_pixmaps = {}
        self.preview_cache = OrderedDict()
        self.preview_cache_bytes = 0
        layout.addWidget(self.library_views, 1)
        nav = QHBoxLayout()
        nav.setSpacing(4)
        nav.addStretch()
        self.library_previous = button("Previous", lambda: self.move_library(-1))
        self.library_next = button("Next", lambda: self.move_library(1))
        self.library_page_group = QButtonGroup(self)
        self.library_page_buttons = []
        nav.addWidget(self.library_previous)
        for number in range(1, 11):
            control = QPushButton(str(number))
            control.setCheckable(True)
            control.setObjectName("pageNumber")
            control.clicked.connect(
                lambda _checked=False, control=control: self.go_to_library_page(int(control.text()))
            )
            self.library_page_group.addButton(control)
            self.library_page_buttons.append(control)
            nav.addWidget(control)
        nav.addWidget(self.library_next)
        self.library_jump = QLineEdit()
        self.library_jump.setPlaceholderText("Page")
        self.library_jump.setAccessibleName("Jump to library page")
        self.library_jump.setMaximumWidth(65)
        self.library_jump_validator = QIntValidator(1, 1, self)
        self.library_jump.setValidator(self.library_jump_validator)
        self.library_jump.returnPressed.connect(self.jump_library)
        nav.addWidget(self.library_jump)
        self.library_jump_button = button("Go", self.jump_library)
        nav.addWidget(self.library_jump_button)
        layout.addLayout(nav)
        selection = QHBoxLayout()
        selection.addStretch()
        self.open_selected_button = button(
            "Open selected movie", lambda: self.open_movie(self.library_table.currentRow())
        )
        selection.addWidget(self.open_selected_button)
        layout.addLayout(selection)
        self.update_library_pagination(1, 1)
        self.stack.addWidget(widget)

    def change_library_view(self, index):
        self.library_views.setCurrentIndex(index)
        self.open_selected_button.setVisible(index == 0)
        if index and not self.library_cards and hasattr(self, "library_movies"):
            self.render_library_cards()
        self.update_library_hint()

    def update_library_hint(self):
        if hasattr(self, "library_movies"):
            hint = (
                "Click a cover or double-click a card for details"
                if self.library_view.currentIndex()
                else "Double-click a row to view details"
            )
            self.library_count.setText(f"{self.library_total} movies")
            self.library_count.setToolTip(hint)

    def reverse_library_sort(self):
        self.sort_library(self.library_sort_column)

    def choose_library_sort(self, index):
        column = self.library_sort_combo.itemData(index)
        if column != self.library_sort_column:
            self.sort_library(column)

    def render_library_cards(self):
        self.library_cards = {}
        for row, movie in enumerate(self.library_movies):

            def open_card(row=row):
                self.library_table.selectRow(row)
                self.open_movie(row)

            card = MovieCard(movie, open_card)
            if row in self.library_pixmaps:
                card.set_cover(self.library_pixmaps[row])
            self.library_cards[row] = card
        self.card_grid.set_cards(list(self.library_cards.values()))
        self.card_scroll.verticalScrollBar().setValue(0)

    def search_library(self):
        self.library_page = 1
        self.load_library()

    def filter_library_by_tag(self, field, value):
        if field not in TAG_LABELS or not value.strip():
            return
        self.library_tag_filter = (field, value)
        self.library_filter_label.setText(f"{TAG_LABELS[field]}: {value}")
        self.library_filter_controls.show()
        self.library_query.clear()
        self.library_page = 1
        self.movie_request_generation += 1  # Ignore pending navigation in the old result set.
        if self.movie_dialog is not None:
            self.movie_dialog.hide()
        if self.navigation.currentRow() == 0:
            self.load_library()
        else:
            self.navigation.setCurrentRow(0)
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def clear_library_filter(self):
        self.library_tag_filter = None
        self.library_filter_controls.hide()
        self.library_page = 1
        self.load_library()

    def sort_library(self, column):
        if column == 0:
            return
        self.library_sort_order = (
            "desc"
            if column == self.library_sort_column and self.library_sort_order == "asc"
            else "asc"
        )
        self.library_sort_column = column
        self.library_sort_combo.setCurrentIndex(self.library_sort_combo.findData(column))
        self.library_table.horizontalHeader().setSortIndicator(
            column,
            Qt.SortOrder.AscendingOrder
            if self.library_sort_order == "asc"
            else Qt.SortOrder.DescendingOrder,
        )
        self.library_order_button.setText("↑" if self.library_sort_order == "asc" else "↓")
        self.library_order_button.setToolTip(
            ("Ascending" if self.library_sort_order == "asc" else "Descending")
            + "; click to reverse"
        )
        self.library_page = 1
        self.load_library()

    def move_library(self, change):
        self.go_to_library_page(self.library_page + change)

    def go_to_library_page(self, number):
        if not 1 <= number <= self.library_pages:
            self.statusBar().showMessage(f"Enter a page from 1 to {self.library_pages}.", 5000)
            return
        if number == self.library_page:
            return
        self.library_page = number
        self.load_library()

    def jump_library(self):
        value = self.library_jump.text().strip()
        if not value or not self.library_jump.hasAcceptableInput():
            self.statusBar().showMessage(f"Enter a page from 1 to {self.library_pages}.", 5000)
            return
        self.go_to_library_page(int(value))

    def update_library_pagination(self, current, pages):
        self.library_page, self.library_pages = current, max(1, pages)
        first = ((current - 1) // 10) * 10 + 1
        for offset, control in enumerate(self.library_page_buttons):
            number = first + offset
            control.setText(str(number))
            control.setVisible(number <= self.library_pages)
            control.setChecked(number == current)
        self.library_previous.setEnabled(current > 1)
        self.library_next.setEnabled(current < self.library_pages)
        self.library_jump_validator.setTop(self.library_pages)
        self.library_jump.setPlaceholderText(f"1–{self.library_pages}")
        self.library_jump.setToolTip(f"Jump to page (1–{self.library_pages}); press Enter or Go")

    def load_library(self):
        self.api.cancel_group("library")
        self.library_generation += 1
        generation = self.library_generation
        parameters = {
            "q": self.library_query.text(),
            "page": self.library_page,
            "sort": (
                {1: "release_date", 2: "product_id", 3: "actresses", 4: "title", 5: "maker"}[
                    self.library_sort_column
                ]
                + "_"
                + self.library_sort_order
            ),
        }
        if self.library_tag_filter is not None:
            parameters["filter_field"], parameters["filter_value"] = self.library_tag_filter
        query = urlencode(parameters)
        self.api.submit(
            "/api/library?" + query,
            lambda result: self.show_library(result, generation, parameters),
            group="library",
        )

    def show_library(self, result, generation, parameters=None):
        if generation != self.library_generation:
            return
        if result["page"] > result["pages"]:
            self.library_page = max(1, result["pages"])
            self.load_library()
            return
        self.library_context = dict(parameters or getattr(self, "library_context", {}))
        self.library_result_page = result["page"]
        self.library_movies = result["items"]
        self.library_total = result["total"]
        self.library_pixmaps = {}
        self.library_cards = {}
        self.card_grid.set_cards([])
        self.library_table.clearContents()
        self.library_table.setUpdatesEnabled(False)
        self.library_table.setRowCount(len(self.library_movies))
        self.update_library_hint()
        self.update_library_pagination(result["page"], result["pages"])
        for row, movie in enumerate(self.library_movies):
            self.library_table.setRowHeight(row, 100)
            values = [
                "",
                movie["streaming_release_date"] or "",
                movie["distribution_product_id"],
                " · ".join(movie["actresses"]),
                movie["title"],
                movie["maker"] or "",
            ]
            for col, value in enumerate(values):
                self.library_table.setItem(row, col, QTableWidgetItem(value))
            cover = movie.get("cover")
            if cover:
                key = (cover["id"], cover["version"])
                if key in self.preview_cache:
                    self.preview_cache.move_to_end(key)
                    self.set_library_preview(self.preview_cache[key], row)
                else:
                    self.api.submit(
                        f"/media/{cover['id']}?preview=true",
                        lambda data, row=row, key=key: self.show_thumbnail(
                            data, row, generation, key
                        ),
                        raw=True,
                        group="library",
                    )
        self.library_table.setUpdatesEnabled(True)
        if self.library_view.currentIndex():
            self.render_library_cards()

    def show_thumbnail(self, data, row, generation, key):
        if generation != self.library_generation:
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            size = pixmap.width() * pixmap.height() * 4
            if key not in self.preview_cache:
                self.preview_cache[key] = pixmap
                self.preview_cache_bytes += size
                while self.preview_cache_bytes > 24 * 1024 * 1024 and self.preview_cache:
                    _old_key, old = self.preview_cache.popitem(last=False)
                    self.preview_cache_bytes -= old.width() * old.height() * 4
            self.set_library_preview(pixmap, row)

    def set_library_preview(self, pixmap, row):
        self.library_pixmaps[row] = pixmap
        if row in self.library_cards:
            self.library_cards[row].set_cover(pixmap)
        image = QLabel()
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image.setPixmap(
            pixmap.scaled(
                140,
                90,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.library_table.setCellWidget(row, 0, image)

    def open_movie(self, row):
        if row < 0 or row >= len(getattr(self, "library_movies", [])):
            return
        self.movie_navigation_context = dict(self.library_context)
        self.movie_navigation_total = self.library_total
        page = self.library_result_page
        self.movie_navigation_pages = {page: list(self.library_movies)}
        self.movie_navigation_index = (page - 1) * 24 + row
        self.request_navigation_movie()

    def navigate_movie(self, direction):
        index = self.movie_navigation_index + direction
        if 0 <= index < self.movie_navigation_total:
            self.movie_navigation_index = index
            self.request_navigation_movie()

    def request_navigation_movie(self):
        self.movie_request_generation += 1
        generation = self.movie_request_generation
        page, row = divmod(self.movie_navigation_index, 24)
        page += 1

        def open_result(result):
            if generation != self.movie_request_generation:
                return
            items = result["items"]
            self.movie_navigation_pages[page] = items
            for old_page in list(self.movie_navigation_pages):
                if abs(old_page - page) > 1:
                    del self.movie_navigation_pages[old_page]
            if row >= len(items):
                self.statusBar().showMessage(
                    "Library results changed; reopen a movie from the library"
                )
                return
            self.api.submit(
                f"/api/movies/{items[row]['id']}",
                lambda movie: self.show_movie(movie, generation),
            )

        if page in self.movie_navigation_pages:
            open_result({"items": self.movie_navigation_pages[page]})
        else:
            parameters = dict(self.movie_navigation_context, page=page)
            self.api.submit("/api/library?" + urlencode(parameters), open_result)

    def show_movie(self, movie, generation=None):
        if generation is not None and generation != self.movie_request_generation:
            return
        if self.movie_dialog is None:
            self.movie_dialog = MovieDetailDialog(
                self,
                Qt.WindowType.Window
                | Qt.WindowType.WindowTitleHint
                | Qt.WindowType.WindowSystemMenuHint
                | Qt.WindowType.WindowMinMaxButtonsHint
                | Qt.WindowType.WindowCloseButtonHint,
            )
            self.movie_dialog.resize(1080, 950)
            QVBoxLayout(self.movie_dialog)
            for key, direction in [(Qt.Key.Key_Left, -1), (Qt.Key.Key_Right, 1)]:
                shortcut = QShortcut(QKeySequence(key), self.movie_dialog)
                shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
                shortcut.activated.connect(
                    lambda direction=direction: self.navigate_movie(direction)
                )
        dialog = self.movie_dialog
        if self.movie_content is not None:
            dialog.layout().removeWidget(self.movie_content)
            self.movie_content.hide()
            self.movie_content.deleteLater()
        self.movie_content = QWidget(dialog)
        dialog.layout().addWidget(self.movie_content)
        self.movie_view_generation += 1
        view_generation = self.movie_view_generation
        dialog.setProperty("content_generation", view_generation)
        dialog.setWindowTitle(movie["distribution_product_id"])
        layout = QVBoxLayout(self.movie_content)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)
        title = QLabel(movie["title"])
        title.setWordWrap(True)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("movieTitle")
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(title)
        summary = QLabel(
            " · ".join(
                str(value)
                for value in (
                    movie["distribution_product_id"],
                    movie.get("streaming_release_date"),
                    movie.get("runtime"),
                )
                if value
            )
        )
        summary.setTextFormat(Qt.TextFormat.PlainText)
        summary.setObjectName("muted")
        summary.setWordWrap(True)
        titles.addWidget(summary)
        header.addLayout(titles, 1)
        refresh = button(
            "Refresh metadata & cover",
            lambda: self.api.submit(
                f"/api/movies/{movie['id']}/refresh-media",
                lambda _result: self.statusBar().showMessage("Movie queued for refresh"),
                {},
            ),
            primary=True,
        )
        header.addWidget(refresh)
        layout.addLayout(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        metadata = QGridLayout(content)
        metadata.setContentsMargins(0, 8, 0, 12)
        metadata.setHorizontalSpacing(28)
        metadata.setVerticalSpacing(18)
        metadata.setColumnStretch(0, 1)
        metadata.setColumnStretch(1, 1)
        cover_image = FittedCover()
        dialog.cover_widget = cover_image
        dialog.fit_cover_area()
        layout.addWidget(cover_image)
        fields = list(TAG_LABELS) + [key for key in FIELD_LABELS if key not in TAG_LABELS]
        for index, key in enumerate(fields):
            label = FIELD_LABELS[key]
            group = self.metadata_group(label, self.movie_metadata_field(key, movie.get(key)))
            metadata.addWidget(group, index // 2, index % 2)
        intro = QLabel(movie["video_intro"] or "—")
        intro.setWordWrap(True)
        intro.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row = (len(FIELD_LABELS) + 1) // 2
        metadata.addWidget(self.metadata_group("Video Intro", intro), row, 0, 1, 2)
        source = QLabel(movie["source_url"] or "—")
        source.setWordWrap(True)
        metadata.addWidget(self.metadata_group("Source URL", source), row + 1, 0, 1, 2)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        controls = QHBoxLayout()
        previous = button("← Previous", lambda: self.navigate_movie(-1))
        previous.setEnabled(getattr(self, "movie_navigation_index", 0) > 0)
        next_movie = button("Next →", lambda: self.navigate_movie(1))
        next_movie.setEnabled(
            getattr(self, "movie_navigation_index", 0) + 1
            < getattr(self, "movie_navigation_total", 1)
        )
        controls.addWidget(previous)
        controls.addWidget(next_movie)
        controls.addStretch()
        layout.addLayout(controls)
        self.api.submit(
            f"/api/media-assets?movie_id={movie['id']}",
            lambda assets: self.load_dialog_cover(assets, cover_image, dialog, view_generation),
        )
        dialog.setWindowState(dialog.windowState() & ~Qt.WindowState.WindowMinimized)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def metadata_group(self, title, field):
        group = QWidget()
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        heading = QLabel(title.upper())
        heading.setObjectName("eyebrow")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(field)
        return group

    def movie_metadata_field(self, key, value):
        values = value if isinstance(value, list) else [value] if value else []
        field = QLabel()
        field.setObjectName("metadata_" + key)
        field.setWordWrap(True)
        field.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if key in TAG_LABELS and values:
            field.setTextFormat(Qt.TextFormat.RichText)
            field.setOpenExternalLinks(False)
            field.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.LinksAccessibleByMouse
                | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
            )
            field.setText(
                " · ".join(
                    f'<a href="{index}" style="color: {ACCENT};">{escape(tag)}</a>'
                    for index, tag in enumerate(values)
                )
            )
            field.setToolTip("Click a value to show matching movies in Library")
            field.linkActivated.connect(
                lambda link: self.filter_library_by_tag(key, values[int(link)])
            )
        else:
            field.setTextFormat(Qt.TextFormat.PlainText)
            field.setText(" · ".join(values) or "—")
        return field

    def load_dialog_cover(self, assets, image, dialog, generation):
        if dialog.property("content_generation") != generation:
            return
        cover = next(
            (a for a in assets if a["status"] == "completed" and a["kind"] == "cover"), None
        )
        if cover:

            def display(data):
                pixmap = QPixmap()
                if (
                    dialog.property("content_generation") == generation
                    and dialog.isVisible()
                    and pixmap.loadFromData(data)
                ):
                    image.setPixmap(pixmap)
                    image.clicked.connect(lambda: self.show_full_cover(data, cover["filename"]))

            self.api.submit(f"/media/{cover['id']}", display, raw=True)

    def show_full_cover(self, data, filename):
        dialog = QDialog(
            self,
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint,
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowTitle(filename)
        dialog.resize(1200, 850)
        layout = QVBoxLayout(dialog)
        controls = QHBoxLayout()
        controls.addWidget(QLabel(filename))
        controls.addStretch()
        controls.addWidget(button("Save original image…", lambda: self.save_bytes(data, filename)))
        layout.addLayout(controls)
        image = FittedCover()
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        image.setPixmap(pixmap)
        layout.addWidget(image, 1)
        self.dialogs.append(dialog)
        dialog.finished.connect(
            lambda _code: self.dialogs.remove(dialog) if dialog in self.dialogs else None
        )
        dialog.show()

    def save_bytes(self, data, filename):
        destination, _filter = QFileDialog.getSaveFileName(self, "Save file", filename)
        if destination:
            try:
                Path(destination).write_bytes(data)
                self.statusBar().showMessage("Saved " + destination)
            except OSError as error:
                self.show_error(error)

    def write_export(self, destination, data):
        try:
            Path(destination).write_bytes(data)
            self.statusBar().showMessage("Saved " + destination)
        except OSError as error:
            self.show_error(error)

    def build_authentication(self):
        widget, layout = page("Website Authentication")
        card = QGroupBox("Website session")
        card_layout = QVBoxLayout(card)
        self.auth_source = QComboBox()
        self.auth_source.addItems(["DMM", "MGS"])
        card_layout.addWidget(self.auth_source)
        card_layout.addWidget(
            QLabel("Requires a Japan IP. Connect to your Japan VPN before opening it.")
        )
        self.auth_status = QLabel("Session: closed")
        card_layout.addWidget(self.auth_status)
        controls = QHBoxLayout()
        self.auth_buttons = [
            button(
                "Open selected website",
                lambda: self.session_action("open:" + self.auth_source.currentText().lower()),
            ),
            button("I completed confirmation / login", lambda: self.session_action("ready")),
            button("Close browser / pause queue", lambda: self.session_action("close")),
        ]
        for control in self.auth_buttons:
            control.setProperty("primary", control == self.auth_buttons[0])
            controls.addWidget(control)
        controls.addStretch()
        card_layout.addLayout(controls)
        self.auth_feedback = QLabel("Complete age confirmation and login inside the browser below.")
        self.auth_feedback.setWordWrap(True)
        card_layout.addWidget(self.auth_feedback)
        layout.addWidget(card)
        self.browser_view = None
        self.browser_layout = layout
        layout.addStretch(0)
        self.stack.addWidget(widget)

    def session_action(self, action):
        for control in self.auth_buttons:
            control.setEnabled(False)
        self.auth_feedback.setText("Working…")

        def finished(result):
            self.auth_status.setText("Session: " + result["status"].replace("_", " "))
            self.auth_feedback.setText("Done.")
            for control in self.auth_buttons:
                control.setEnabled(True)

        self.api.submit("/api/session/" + action, finished, {})
        QTimer.singleShot(
            66000, lambda: [control.setEnabled(True) for control in self.auth_buttons]
        )

    def show_browser_page(self, browser_page):
        if self.browser_view is None:
            self.browser_view = QWebEngineView()
            self.browser_layout.addWidget(self.browser_view, 1)
        self.browser_view.setPage(browser_page)
        self.browser_view.show()
        self.navigation.setCurrentRow(1)

    def browser_page_closed(self, browser_page):
        if self.browser_view is not None and self.browser_view.page() is browser_page:
            self.browser_layout.removeWidget(self.browser_view)
            self.browser_view.hide()
            self.browser_view.deleteLater()
            self.browser_view = None

    def build_search(self):
        widget, layout = page("Search Product URLs")
        row, self.product_query, self.search_button = self.search_row(self.start_search)
        self.search_source = QComboBox()
        self.search_source.addItems(["DMM", "MGS"])
        row.insertWidget(0, self.search_source)
        self.product_query.setPlaceholderText("Actress name, product ID, maker or other keyword")
        layout.addLayout(row)
        self.search_feedback = QLabel()
        layout.addWidget(self.search_feedback)
        self.search_results = QGroupBox("Product URLs")
        results_layout = QVBoxLayout(self.search_results)
        controls = QHBoxLayout()
        controls.addWidget(
            button(
                "Copy this page",
                lambda: QApplication.clipboard().setText(self.urls_result.toPlainText()),
            )
        )
        controls.addWidget(button("Save all collected URLs…", self.save_search_urls))
        controls.addStretch()
        results_layout.addLayout(controls)
        self.urls_result = QTextEdit()
        self.urls_result.setReadOnly(True)
        results_layout.addWidget(self.urls_result)
        nav = QHBoxLayout()
        self.search_previous = button("Previous", lambda: self.move_search(-1))
        self.search_next = button("Next", lambda: self.move_search(1))
        self.search_label = QLabel()
        nav.addWidget(self.search_previous)
        nav.addWidget(self.search_label)
        nav.addWidget(self.search_next)
        nav.addStretch()
        results_layout.addLayout(nav)
        layout.addWidget(self.search_results, 1)
        self.search_results.hide()
        layout.addStretch(0)
        self.stack.addWidget(widget)

    def start_search(self):
        term = self.product_query.text().strip()
        if not term or self.search_running:
            return
        self.search_page = 1
        self.search_button.setEnabled(False)
        self.search_results.hide()
        self.search_feedback.setText("Starting " + self.search_source.currentText() + " search…")
        self.search_running = True

        def started(result):
            self.search_id = result["id"]
            self.load_search()

        self.api.submit(
            "/api/product-searches",
            started,
            {"query": term, "source": self.search_source.currentText().lower()},
        )

    def load_search(self):
        if self.search_id and not self.closing:
            self.api.submit(
                f"/api/product-searches/{self.search_id}?page={self.search_page}", self.show_search
            )

    def show_search(self, result):
        self.search_results.show()
        self.urls_result.setPlainText("\n".join(result["urls"]))
        self.search_label.setText(f"Page {result['page']} of {result['pages']}")
        self.search_previous.setEnabled(result["page"] > 1)
        self.search_next.setEnabled(result["page"] < result["pages"])
        self.search_running = result["status"] == "running"
        self.search_button.setEnabled(not self.search_running)
        if self.search_running:
            self.search_feedback.setText(
                f"{result['total']} URLs collected · {result['source_pages']} source pages crawled"
            )
            self.search_timer.start(1500)
        else:
            self.search_feedback.setText(
                f"Search {result['status']} · {result['total']} unique URLs · 100 per page"
                + (" · " + result["error"] if result.get("error") else "")
            )

    def move_search(self, change):
        self.search_timer.stop()
        self.search_page += change
        self.load_search()

    def save_search_urls(self):
        if self.search_id:
            destination, _filter = QFileDialog.getSaveFileName(
                self, "Save URLs", "product-urls.txt", "Text (*.txt)"
            )
            if destination:
                self.api.submit(
                    f"/api/product-searches/{self.search_id}/download",
                    lambda data: self.write_export(destination, data),
                    raw=True,
                )

    def build_storage(self):
        widget, layout = page("Database & Library")
        storage = QGroupBox("Storage")
        form = QFormLayout(storage)
        database = QLabel(str(self.settings.database_path))
        database.setWordWrap(True)
        form.addRow("Database", database)
        self.library_folders = table(["Library", "Folder", ""])
        self.library_folders.horizontalHeader().setStretchLastSection(False)
        self.library_folders.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.library_folders.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed
        )
        self.library_folders.setColumnWidth(2, 96)
        self.library_folders.setMinimumHeight(180)
        form.addRow(self.library_folders)
        note = QLabel("Removing a library removes its movies from this app. Files stay on disk.")
        note.setWordWrap(True)
        form.addRow(note)
        self.storage_busy = False
        self.add_library_button = button("Add library folder…", self.add_folder, primary=True)
        self.refresh_library_button = button("Refresh Library", self.refresh_library)
        storage_controls = QHBoxLayout()
        storage_controls.addWidget(self.add_library_button)
        storage_controls.addWidget(self.refresh_library_button)
        storage_controls.addStretch()
        form.addRow(storage_controls)
        self.storage_feedback = QLabel()
        self.storage_feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.storage_feedback.setWordWrap(True)
        form.addRow(self.storage_feedback)
        layout.addWidget(storage)
        layout.addStretch()
        self.stack.addWidget(widget)

    def build_scraping(self):
        widget, outer = page("Scraping & Downloads")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        card = QGroupBox("Paste product URLs")
        card_layout = QVBoxLayout(card)
        self.pasted_urls = QTextEdit()
        self.pasted_urls.setPlaceholderText("One DMM or MGS product URL per line (up to 100)")
        self.pasted_urls.setMinimumHeight(135)
        self.pasted_urls.setMaximumHeight(160)
        card_layout.addWidget(self.pasted_urls)
        self.target_folder = QComboBox()
        card_layout.addWidget(self.target_folder)
        controls = QHBoxLayout()
        self.enqueue_button = button("Add to scrape queue", self.enqueue_urls, primary=True)
        controls.addWidget(self.enqueue_button)
        controls.addWidget(
            button(
                "Clear finished URL history",
                lambda: self.api.submit(
                    "/api/scrape-history/clear", lambda _result: self.refresh_status(), {}
                ),
            )
        )
        controls.addStretch()
        card_layout.addLayout(controls)
        self.jobs_table = table(["ID", "Status", "Product URL", "Error", "Retry"])
        self.jobs_table.setMinimumHeight(230)
        card_layout.addWidget(self.jobs_table)
        layout.addWidget(card)
        downloads = QGroupBox("Cover downloads")
        download_layout = QVBoxLayout(downloads)
        controls = QHBoxLayout()
        controls.addWidget(
            button("Pause", lambda: self.api.submit("/api/downloads/pause", body={}))
        )
        controls.addWidget(
            button("Resume", lambda: self.api.submit("/api/downloads/resume", body={}))
        )
        controls.addWidget(
            button(
                "Clear finished download history",
                lambda: self.api.submit(
                    "/api/download-history/clear", lambda _result: self.refresh_status(), {}
                ),
            )
        )
        controls.addStretch()
        download_layout.addLayout(controls)
        self.covers_table = table(
            ["ID", "Filename", "Status", "Progress", "Resolution", "Error", "Retry"]
        )
        self.covers_table.setMinimumHeight(230)
        download_layout.addWidget(self.covers_table)
        layout.addWidget(downloads)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.stack.addWidget(widget)

    def show_folders(self, folders):
        selected = self.target_folder.currentData()
        self.target_folder.clear()
        names = [folder["label"] for folder in folders]
        self.sidebar_libraries.setText(
            "\n".join(names[:3]) + (f"\n+{len(names) - 3} more" if len(names) > 3 else "")
            if names
            else "No libraries added"
        )
        self.sidebar_libraries.setToolTip("\n".join(folder["path"] for folder in folders))
        self.library_folders.setRowCount(len(folders))
        for row, folder in enumerate(folders):
            self.library_folders.setItem(row, 0, QTableWidgetItem(folder["label"]))
            self.library_folders.setItem(row, 1, QTableWidgetItem(folder["path"]))
            remove = button("Remove", lambda f=folder: self.remove_folder(f))
            remove.setAccessibleName("Remove library " + folder["label"])
            remove.setToolTip("Remove from jav-data; keep all files on disk")
            self.library_folders.setCellWidget(row, 2, remove)
            self.library_folders.setRowHeight(row, 48)
            self.target_folder.addItem(folder["label"] + " — " + folder["path"], folder["id"])
        index = self.target_folder.findData(selected)
        if index >= 0:
            self.target_folder.setCurrentIndex(index)
        self.set_storage_busy(self.storage_busy)

    def remove_folder(self, folder):
        self.set_storage_busy(True)
        self.storage_feedback.setText(f"Removing library {folder['label']}…")

        def removed(result):
            self.show_folders(result["folders"])
            self.library_refreshed({"removed": result["removed"]})
            self.storage_feedback.setText(
                f"Removed library {folder['label']} and {result['removed']} movies from the app. "
                "Files remain on disk."
            )
            self.storage_feedback.setToolTip("")

        self.api.submit(
            f"/api/product-folders/{folder['id']}/remove", removed, {}, on_error=self.storage_failed
        )

    def add_folder(self):
        selected = QFileDialog.getExistingDirectory(self, "Choose a library folder")
        if selected:
            self.set_storage_busy(True)
            self.storage_feedback.setText("Adding and scanning library…")

            def added(result):
                self.show_folders(result)
                report = next((item["scan"] for item in result if "scan" in item), {})
                self.library_refreshed(report)

            self.api.submit(
                "/api/product-folders", added, {"path": selected}, on_error=self.storage_failed
            )

    def set_storage_busy(self, busy):
        self.storage_busy = busy
        self.add_library_button.setEnabled(not busy)
        self.refresh_library_button.setEnabled(not busy)
        self.library_folders.setEnabled(not busy)
        self.target_folder.setEnabled(not busy and self.target_folder.count() > 0)
        self.enqueue_button.setEnabled(not busy and self.target_folder.count() > 0)
        self.enqueue_button.setToolTip(
            "" if self.target_folder.count() else "Add a library folder in Database & Library first"
        )

    def refresh_library(self):
        self.set_storage_busy(True)
        self.storage_feedback.setText("Scanning libraries and updating the database…")
        self.api.submit(
            "/api/product-folders/refresh", self.library_refreshed, {}, on_error=self.storage_failed
        )

    def storage_failed(self, error):
        self.set_storage_busy(False)
        self.storage_feedback.setText(str(error))
        self.statusBar().showMessage(str(error), 15000)

    def library_refreshed(self, report):
        self.set_storage_busy(False)
        message = (
            f"Library updated: {report.get('added', 0)} added, "
            f"{report.get('updated', 0)} updated, {report.get('removed', 0)} removed, "
            f"{report.get('skipped', 0)} skipped."
        )
        warnings = report.get("warnings", [])
        details = "\n".join(warnings[:3])
        if len(warnings) > 3:
            details += f"\n{len(warnings) - 3} more warnings."
        self.storage_feedback.setText(message + ("\n" + details if details else ""))
        self.storage_feedback.setToolTip("\n".join(warnings))
        self.statusBar().showMessage(message, 15000)
        self.preview_cache.clear()
        self.preview_cache_bytes = 0
        self.library_page = 1
        self.load_library()
        self.refresh_status()

    def enqueue_urls(self):
        urls = [url.strip() for url in self.pasted_urls.toPlainText().splitlines() if url.strip()]
        if not urls:
            return
        self.api.submit(
            "/api/scrape-jobs",
            lambda _result: self.refresh_status(),
            {"urls": urls, "product_folder_id": self.target_folder.currentData()},
        )

    def refresh_status(self):
        if self.closing or self.isMinimized() or not self.isVisible():
            return
        if self.stack.currentIndex() == 1:
            self.api.submit(
                "/api/session",
                lambda result: self.auth_status.setText(
                    "Session: " + result["status"].replace("_", " ")
                ),
                once=True,
            )
        if self.stack.currentIndex() == 3:
            self.api.submit("/api/scrape-jobs", self.show_jobs, once=True)
            self.api.submit("/api/media-assets?history=true", self.show_covers, once=True)

    def show_jobs(self, jobs):
        if jobs == getattr(self, "last_jobs", None):
            return
        self.last_jobs = jobs
        self.jobs_table.clearContents()
        self.jobs_table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            for col, value in enumerate([job["id"], job["status"], job["url"], job["error"] or ""]):
                self.jobs_table.setItem(row, col, QTableWidgetItem(str(value)))
            if job["status"] in ("failed", "awaiting_session", "completed"):
                self.jobs_table.setCellWidget(
                    row,
                    4,
                    button(
                        "Retry",
                        lambda job_id=job["id"]: self.api.submit(
                            f"/api/scrape-jobs/{job_id}/retry", lambda _r: self.refresh_status(), {}
                        ),
                    ),
                )

    def show_covers(self, assets):
        if assets == getattr(self, "last_covers", None):
            return
        self.last_covers = assets
        self.covers_table.clearContents()
        self.covers_table.setRowCount(len(assets))
        for row, asset in enumerate(assets):
            total = asset["total_bytes"]
            progress = f"{asset['downloaded_bytes'] / 1024:.0f} KB" + (
                f" / {total / 1024:.0f} KB" if total else ""
            )
            values = [
                len(assets) - row,
                asset["filename"],
                asset["status"],
                progress,
                f"{asset['width']} × {asset['height']}" if asset["width"] else "—",
                asset["error"] or "",
            ]
            for col, value in enumerate(values):
                self.covers_table.setItem(row, col, QTableWidgetItem(str(value)))
            if asset["status"] == "failed":
                self.covers_table.setCellWidget(
                    row,
                    6,
                    button(
                        "Retry",
                        lambda asset_id=asset["id"]: self.api.submit(
                            f"/api/media-assets/{asset_id}/retry",
                            lambda _r: self.refresh_status(),
                            {},
                        ),
                    ),
                )

    def closeEvent(self, event):
        event.ignore()
        if self.closing:
            return
        self.closing = True
        self.refresh_timer.stop()
        self.search_timer.stop()
        self.hide()
        self.backend.stop()
        self.shutdown_timer = QTimer(self)
        self.shutdown_timer.timeout.connect(self.finish_shutdown)
        self.shutdown_timer.start(100)

    def finish_shutdown(self):
        if not self.backend.thread.is_alive():
            self.shutdown_timer.stop()
            self.api.pool.shutdown(wait=False, cancel_futures=True)
            self.api.preview_pool.shutdown(wait=False, cancel_futures=True)
            QApplication.instance().quit()

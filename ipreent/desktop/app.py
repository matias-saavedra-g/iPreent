"""iPreent for Windows: main window, tray menu, global hotkey and the print-dialog bridge."""
import ctypes
import ctypes.wintypes
import io
import json
import os
import secrets
import socket
import sys
import time
import winreg
from pathlib import Path

from PIL import Image
from PySide6.QtCore import (QAbstractAnimation, QAbstractNativeEventFilter, QBuffer, QEasingCurve,
                            QIODevice, QPoint, QPointF, QRectF, QSettings, QSize, Qt, QTimer,
                            QVariantAnimation)
from PySide6.QtGui import (QAction, QActionGroup, QBrush, QColor, QFont, QFontDatabase, QGuiApplication,
                           QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSlider, QSpinBox, QStackedWidget,
                               QSystemTrayIcon, QTableWidget, QTableWidgetItem, QToolButton,
                               QVBoxLayout, QWidget)

from .. import api, busy, config, convert, features, imaging, protocol, receipt
from ..cli import ENERGY_PRESETS
from ..models import lookup
from . import spool
from .server import Server
from .worker import Worker

APP = "iPreent"
HERE = Path(__file__).parent
DARKNESS = list(ENERGY_PRESETS.values())          # slider 1..5
DARKNESS_NAMES = ["Lightest", "Lighter", "Normal", "Darker", "Darkest"]
# key: (label, Segoe Fluent / MDL2 icon glyph). The nav order comes from features.DESKTOP.
MODES = {"photo": ("Photo", "\uE91B"), "document": ("Document", "\uE8A5"), "text": ("Text", "\uE8D2"),
         "receipt": ("Receipt", "\uE719"), "list": ("Checklist", "\uE9D5"), "qr": ("QR code", "\uED14"),
         "banner": ("Banner", "\uE7C1"), "barcode": ("Barcode", "\uE8EC")}
OLD_MODES = ["photo", "text", "list", "banner", "qr", "barcode", "receipt"]   # saved as a row number before 0.5
GLYPH_SETTINGS, GLYPH_PRINTER = "\uE713", "\uE749"
ICON_FONTS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# Fluent look: Qt's "windows11" style draws the controls; this adds Mica-friendly panels and
# uses the system accent colour, so light/dark and accent follow Windows settings live.
STYLE = """
QMainWindow, QWidget#central { background: transparent; }
QWidget#side, QWidget#settings { background: transparent; }
QFrame#card { background: palette(base); border: 1px solid palette(midlight); border-radius: 8px; }
QLabel#section { font-weight: 600; color: palette(placeholder-text); padding-top: 8px; }
QLabel#drop { background: palette(base); border: 1px dashed palette(mid); border-radius: 8px; padding: 18px; }
QListWidget#nav, QListWidget#queue { border: none; background: transparent; }
QListWidget#queue::item { padding: 4px 6px; border-radius: 4px; }
QFrame#card:hover { border-color: palette(mid); }
QToolButton#gear { border: none; border-radius: 4px; padding: 4px; }
QToolButton#gear:hover { background: palette(midlight); }
QLabel#subtle { color: palette(placeholder-text); }
QListWidget#nav::item { height: 36px; padding-left: 8px; border-radius: 4px; margin: 1px 0; }
QListWidget#nav::item:hover { background: palette(midlight); }
QListWidget#nav::item:selected { background: palette(midlight); color: palette(text); font-weight: 600;
                                 border-left: 3px solid palette(accent); }
QPushButton#print { background: palette(accent); color: palette(button-text); border: none;
                    border-radius: 4px; font-size: 14px; font-weight: 600; min-height: 40px; }
QPushButton#print:hover { background: palette(highlight); }
QPushButton#print:disabled { background: palette(midlight); color: palette(placeholder-text); }
QScrollArea#paperArea, QScrollArea#paperArea > QWidget > QWidget { background: transparent; border: none; }
"""


def windows_build():
    return sys.getwindowsversion().build


def accent_text():
    """Black or white text on the accent colour, whichever reads better (like Windows does)."""
    c = QGuiApplication.palette().accent().color()
    return "black" if 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue() > 150 else "white"


def mica_supported():
    return windows_build() >= 22621


def fluent_window(widget):
    """Mica backdrop and a title bar that matches the light/dark setting (Windows 11)."""
    hwnd = int(widget.winId())
    dwm = ctypes.windll.dwmapi
    dark = ctypes.c_int(int(QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark))
    dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), 4)          # immersive dark mode
    if mica_supported():
        mica = ctypes.c_int(2)                                          # DWMSBT_MAINWINDOW
        dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(mica), 4)
        margins = (ctypes.c_int * 4)(-1, -1, -1, -1)                    # backdrop under the whole client area
        dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))


def icon_font(size=12):
    """Windows' own icon font (Fluent on 11, MDL2 on 10), or None where it isn't installed."""
    have = set(QFontDatabase.families())
    for fam in ICON_FONTS:
        if fam in have:
            f = QFont(fam)
            f.setPixelSize(size)
            return f
    return None


def glyph_icon(glyph, size=20, color=None):
    font = icon_font(size)
    if font is None:
        return QIcon()
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    qp = QPainter(pm)
    qp.setFont(font)
    qp.setPen(color or QGuiApplication.palette().text().color())
    qp.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, glyph)
    qp.end()
    return QIcon(pm)


def ticket_pixmap(color, w=26, h=34):
    """A little paper slip, the thing that flies from Print to the queue."""
    pm = QPixmap(w * 2, h * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    qp = QPainter(pm)
    qp.setRenderHint(QPainter.Antialiasing)
    qp.setPen(Qt.NoPen)
    qp.setBrush(color)
    qp.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 4, 4)
    qp.setBrush(QColor(255, 255, 255, 220))
    for i, frac in enumerate((0.7, 0.5, 0.6)):
        qp.drawRoundedRect(QRectF(6, 8 + i * 7, (w - 12) * frac, 3), 1.5, 1.5)
    qp.end()
    return pm


class ClickFrame(QFrame):
    """A card that does something when clicked anywhere on it."""
    def __init__(self, on_click, **kw):
        super().__init__(**kw)
        self.on_click = on_click
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.on_click()
        super().mouseReleaseEvent(e)


def icon():
    ic = QIcon(str(HERE / "icons" / "icon.svg"))
    ic.addFile(str(HERE / "icons" / "icon-small.svg"))
    return ic


def qimage_from_rows(rows, width):
    h = max(1, len(rows))
    data = bytes(0 if v else 255 for r in rows for v in r) or bytes([255] * width)
    return QImage(data, width, h, width, QImage.Format_Grayscale8).copy()


def pil_from_qimage(qimg):
    buf = QBuffer()
    buf.open(QIODevice.ReadWrite)
    qimg.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).copy()


def parse_pages(spec):
    pages = set()
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        a, _, b = part.partition("-")
        pages.update(range(int(a), int(b or a) + 1))
    return pages or None


def pdf_images(path, width, pages=None, trim=False):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path if isinstance(path, bytes) else str(path))
    for i in range(len(doc)):
        if pages and i + 1 not in pages:
            continue
        page = doc[i]
        # Trimming keeps only part of the page, so render bigger to stay sharp after scaling up.
        target = width * (5 if trim else 2)
        img = page.render(scale=target / page.get_width()).to_pil()
        if trim:
            img = imaging.trim(img)
            if img is None:      # blank page
                continue
        yield img


# ---- global hotkey (Ctrl+Alt+P) ----------------------------------------------------------------

class HotkeyFilter(QAbstractNativeEventFilter):
    WM_HOTKEY = 0x0312

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        ok = ctypes.windll.user32.RegisterHotKey(None, 1, 0x0001 | 0x0002 | 0x4000, ord("P"))
        self.registered = bool(ok)

    def nativeEventFilter(self, etype, message):
        if etype == b"windows_generic_MSG" or etype == "windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == self.WM_HOTKEY and msg.wParam == 1:
                QTimer.singleShot(0, self.callback)
                return True, 0
        return False, 0


# ---- choose printer --------------------------------------------------------------------------

class PrinterDialog(QDialog):
    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose printer")
        self.worker = worker
        self.list = QListWidget()
        self.info = QLabel("Turn the printer on and close the phone app, then scan.")
        self.info.setWordWrap(True)
        scan = QPushButton("Scan")
        scan.clicked.connect(self.scan)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        lay = QVBoxLayout(self)
        for w in (self.info, self.list, scan, buttons):
            lay.addWidget(w)
        worker.found.connect(self.show_found)
        self.resize(380, 320)
        self.scan()

    def scan(self):
        self.list.clear()
        self.info.setText("Scanning…")
        self.worker.scan()

    def show_found(self, found):
        self.list.clear()
        for name, addr, model in found:
            it = QListWidgetItem(f"{name or '(no name)'}   ·   {model}   ·   {addr}")
            it.setData(Qt.UserRole, (name, addr))
            self.list.addItem(it)
        self.info.setText(f"Found {len(found)} printer(s)." if found else
                          "No printers found. Is it on, and not connected to the phone?")
        if found:
            self.list.setCurrentRow(0)

    def chosen(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None


# ---- main window -----------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, worker, settings):
        super().__init__()
        self.worker, self.settings = worker, settings
        self.sources = {"photo": [], "document": []}     # [(label, path or PIL image)] per mode
        self._cache = {}                                  # mode -> (key, images)
        self.rows = []
        self.jobs = {}               # job id -> what the queue shows (see job_queued)
        try:
            self.usage = json.loads(settings.value("usage", "{}"))
        except (TypeError, ValueError):
            self.usage = {}
        self.setWindowTitle(APP)
        self.setWindowIcon(icon())
        self.setAcceptDrops(True)
        self.resize(1180, 760)
        self.debounce = QTimer(self, singleShot=True, interval=150, timeout=self.render)

        root = QWidget(objectName="central")
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._left())
        lay.addWidget(self._center(), 1)
        lay.addWidget(self._right())
        self.setCentralWidget(root)
        if mica_supported():
            self.setAttribute(Qt.WA_TranslucentBackground)

        QShortcut(QKeySequence.Paste, self, activated=self.paste)
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self.print_now)
        QShortcut(QKeySequence.Open, self, activated=self.open_files)

        mode = settings.value("mode_key")
        if mode not in MODES:
            try:
                mode = OLD_MODES[int(settings.value("mode", 0))]
            except (TypeError, ValueError, IndexError):
                mode = None
        self.set_mode(mode or self.order[0])
        self.update_printer({})
        self.schedule()
        self.ticker = QTimer(self, interval=1000, timeout=self.refresh_queue)
        self.ticker.start()

    # -- layout --

    def _section(self, text):
        lab = QLabel(text.upper())
        lab.setObjectName("section")
        return lab

    def _left(self):
        w = QWidget(objectName="side")
        w.setFixedWidth(260)
        lay = QVBoxLayout(w)
        # Printer card: the whole card and its gear open the printer settings (darkness, status,
        # change, feed, forget), so it reads as something you can click.
        card = ClickFrame(self.printer_menu, objectName="card")
        card.setToolTip("Printer settings")
        cl = QVBoxLayout(card)
        top = QHBoxLayout()
        self.p_icon = QLabel()
        self.p_name = QLabel()
        self.p_name.setStyleSheet("font-weight: 600; font-size: 14px")
        self.gear = QToolButton(objectName="gear", toolTip="Printer settings", cursor=Qt.PointingHandCursor)
        if icon_font():
            self.gear.setIcon(glyph_icon(GLYPH_SETTINGS, 18))
            self.gear.setIconSize(QSize(18, 18))
            self.p_icon.setPixmap(glyph_icon(GLYPH_PRINTER, 18).pixmap(18, 18))
        else:
            self.gear.setText("\u2699")
        self.gear.clicked.connect(self.printer_menu)
        top.addWidget(self.p_icon)
        top.addWidget(self.p_name, 1)
        top.addWidget(self.gear)
        self.p_state = QLabel(wordWrap=True)
        self.p_dark = QLabel(objectName="subtle")
        self.pick = QPushButton("Choose printer…")
        self.pick.clicked.connect(self.choose_printer)
        cl.addLayout(top)
        cl.addWidget(self.p_state)
        cl.addWidget(self.p_dark)
        cl.addWidget(self.pick)
        lay.addWidget(card)

        # Tools, most likely first. The order is worked out once at start-up (features.py) so
        # nothing moves while you're using it.
        lay.addWidget(self._section("Create"))
        self.nav = QListWidget(objectName="nav")
        self.order = features.ranked(features.DESKTOP, self.usage)
        self.nav.setIconSize(QSize(18, 18))
        for key in self.order:
            label, glyph = MODES[key]
            it = QListWidgetItem(glyph_icon(glyph, 18), label)
            it.setData(Qt.UserRole, key)
            self.nav.addItem(it)
        self.nav.setFixedHeight(len(MODES) * 38 + 6)
        self.nav.currentRowChanged.connect(self.mode_changed)
        lay.addWidget(self.nav)

        head = QHBoxLayout()
        head.addWidget(self._section("Queue"))
        head.addStretch(1)
        self.queue_summary = QLabel(objectName="subtle")
        self.queue_summary.setStyleSheet("padding-top: 8px")
        head.addWidget(self.queue_summary)
        lay.addLayout(head)
        self.queue = QListWidget(objectName="queue", wordWrap=True)
        lay.addWidget(self.queue, 1)
        return w

    def printer_menu(self):
        m = QMenu(self)
        dark = m.addMenu("Darkness")
        group = QActionGroup(dark)
        for i, name in enumerate(DARKNESS_NAMES, 1):
            a = dark.addAction(name)
            a.setCheckable(True)
            a.setChecked(self.dark.value() == i)
            a.triggered.connect(lambda _=False, i=i: self.dark.setValue(i))
            group.addAction(a)
        m.addAction("Check status and battery", self.worker.refresh)
        details = m.addAction("Printer details…", self.show_details)
        details.setEnabled(bool(config.load().get("name")))
        m.addAction("Change printer…", self.choose_printer)
        m.addAction("Feed paper", self.worker.feed)
        m.addSeparator()
        forget = m.addAction("Forget this printer", self.forget_printer)
        forget.setEnabled(bool(config.load().get("name")))
        m.popup(self.gear.mapToGlobal(QPoint(0, self.gear.height())))
        return m

    def show_details(self):
        """Paper to buy, print width, resolution and speed of the remembered printer."""
        cfg = config.load()
        m = self.model()
        rows = "".join(f"<tr><td style='padding-right:12px'><b>{label}</b></td><td>{value}</td></tr>"
                       for label, value in api.printer_details(m))
        QMessageBox.information(self, "Printer details",
                                f"<p>{cfg.get('name', m.name)} ({m.name} profile)</p><table>{rows}</table>")

    def forget_printer(self):
        config.forget()
        self.update_printer({})

    def _center(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 8)
        self.editors = QStackedWidget()

        self.editor_of = {}

        def add(key, widget):
            self.editor_of[key] = self.editors.addWidget(widget)

        # Photo and Document: the two most used, each with its own file list and defaults
        self.files_label = {}
        add("photo", self._files_editor("photo", "Drop photos or pictures here, or paste one with Ctrl+V"))
        add("document", self._files_editor("document", "Drop PDFs or text files here, or print from any app\n"
                                                       "with File › Print › iPreent"))

        # Text
        self.text = QPlainTextEdit(placeholderText="Type something to print…")
        self.text_size = QSpinBox(minimum=12, maximum=120, value=28, suffix=" px")
        add("text", self._editor(self.text, ("Size", self.text_size)))

        # Checklist
        self.list_title = QLineEdit(placeholderText="Title (optional)")
        self.list_items = QPlainTextEdit(placeholderText="One item per line")
        cw = QWidget()
        cl = QVBoxLayout(cw)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.list_title)
        cl.addWidget(self.list_items)
        add("list", cw)

        # Banner, QR
        self.banner = QLineEdit(placeholderText="Banner text (prints along the paper)")
        self.qr = QLineEdit(placeholderText="Link or text for the QR code")
        add("banner", self._editor(self.banner))
        add("qr", self._editor(self.qr))

        # Barcode
        self.barcode = QLineEdit(placeholderText="Product code, order number… (Code 128)")
        self.barcode_error = QLabel()
        self.barcode_error.setStyleSheet("color: palette(placeholder-text)")
        bw = self._editor(self.barcode)
        bw.layout().insertWidget(1, self.barcode_error)
        add("barcode", bw)
        self.barcode.textChanged.connect(self.schedule)
        add("receipt", self._receipt_editor())
        for e in (self.text, self.list_items):
            e.textChanged.connect(self.schedule)
        for e in (self.list_title, self.banner, self.qr):
            e.textChanged.connect(self.schedule)
        self.text_size.valueChanged.connect(self.schedule)
        self.editors.setMaximumHeight(200)
        lay.addWidget(self.editors)

        self.paper = QLabel(alignment=Qt.AlignHCenter | Qt.AlignTop)
        self.paper.setStyleSheet("background: white; color: #555; padding: 12px 8px 20px 8px; "
                                 "border: 1px solid rgba(0,0,0,0.12); border-radius: 2px;")
        area = QScrollArea(objectName="paperArea", widgetResizable=True)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.addWidget(self.paper, 0, Qt.AlignHCenter | Qt.AlignTop)
        hl.addStretch(1)
        area.setWidget(holder)
        lay.addWidget(area, 1)
        self.caption = QLabel(alignment=Qt.AlignCenter)
        self.caption.setStyleSheet("font-family: Consolas, monospace; font-size: 11px")
        lay.addWidget(self.caption)
        return w

    def _files_editor(self, kind, hint):
        w = QWidget()
        fl = QVBoxLayout(w)
        fl.setContentsMargins(0, 0, 0, 0)
        drop = QLabel(hint, objectName="drop", alignment=Qt.AlignCenter)
        fr = QHBoxLayout()
        self.files_label[kind] = QLabel(wordWrap=True)
        openb = QPushButton("Open…")
        openb.clicked.connect(self.open_files)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: (self.sources[kind].clear(), self.schedule()))
        fr.addWidget(self.files_label[kind], 1)
        fr.addWidget(openb)
        fr.addWidget(clear)
        fl.addWidget(drop)
        fl.addLayout(fr)
        return w

    def _receipt_editor(self):
        """Business details on the left, products table on the right. All remembered."""
        s = self.settings
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.r_business = QLineEdit(s.value("receipt_business", ""), placeholderText="Business name")
        self.r_address = QLineEdit(s.value("receipt_address", ""), placeholderText="Street, city")
        self.r_url = QLineEdit(s.value("receipt_url", ""), placeholderText="example.cl")
        self.r_footer = QLineEdit(s.value("receipt_footer", receipt.DEFAULT_FOOTER),
                                  placeholderText="Message at the bottom")
        form.addRow("Business", self.r_business)
        form.addRow("Address", self.r_address)
        form.addRow("Website", self.r_url)
        form.addRow("Footer", self.r_footer)
        self.r_total = QLabel()
        self.r_total.setStyleSheet("font-weight: 700; font-size: 18px")
        self.r_error = QLabel(wordWrap=True)
        self.r_error.setStyleSheet("color: palette(placeholder-text)")
        form.addRow(self.r_total)
        form.addRow(self.r_error)
        lay.addLayout(form, 2)

        side = QVBoxLayout()
        self.r_items = QTableWidget(0, 3)
        self.r_items.setHorizontalHeaderLabels(["Product", "Qty", "Price (CLP)"])
        head = self.r_items.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 56), (2, 100)):
            head.setSectionResizeMode(col, QHeaderView.Fixed)
            self.r_items.setColumnWidth(col, width)
        self.r_items.verticalHeader().setDefaultSectionSize(28)
        self.r_items.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.r_items.setEditTriggers(QAbstractItemView.AllEditTriggers)
        try:
            rows = json.loads(s.value("receipt_items", "[]"))
        except ValueError:
            rows = []
        for name, qty, price in rows or [("", "1", "")]:
            self.add_receipt_row(name, qty, price, focus=False)
        self.r_items.itemChanged.connect(self.schedule)
        buttons = QHBoxLayout()
        add = QPushButton("Add product")
        add.clicked.connect(lambda: self.add_receipt_row())
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_receipt_rows)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        side.addWidget(self.r_items, 1)
        side.addLayout(buttons)
        lay.addLayout(side, 3)
        for e in (self.r_business, self.r_address, self.r_url, self.r_footer):
            e.textChanged.connect(self.schedule)
        return w

    def add_receipt_row(self, name="", qty="1", price="", focus=True):
        t = self.r_items
        r = t.rowCount()
        t.blockSignals(True)
        t.insertRow(r)
        for col, value in enumerate((name, qty, price)):
            item = QTableWidgetItem(str(value))
            if col:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t.setItem(r, col, item)
        t.blockSignals(False)
        if focus:
            t.setCurrentCell(r, 0)
            t.editItem(t.item(r, 0))
            self.schedule()

    def remove_receipt_rows(self):
        t = self.r_items
        rows = sorted({i.row() for i in t.selectedIndexes()} or {t.currentRow()}, reverse=True)
        for r in rows:
            if r >= 0:
                t.removeRow(r)
        if not t.rowCount():
            self.add_receipt_row(focus=False)
        self.schedule()

    def receipt_rows(self):
        """[(name, qty, price)] as typed, empty rows left out."""
        t = self.r_items
        out = []
        for r in range(t.rowCount()):
            cells = [(t.item(r, c).text().strip() if t.item(r, c) else "") for c in range(3)]
            if cells[0] or cells[2]:
                out.append(tuple(cells))
        return out

    def receipt(self):
        """Receipt from the editor, or None (with the reason shown) when it can't be made yet."""
        self.r_error.setText("")
        self.r_total.setText("")
        items = []
        for n, (name, qty, price) in enumerate(self.receipt_rows(), 1):
            try:
                if not name:
                    raise ValueError("no product name")
                if not price:
                    raise ValueError("no price")
                items.append(receipt.Item(name, price, qty or 1))
            except ValueError as e:
                self.r_error.setText(f"Row {n}: {e}")
                return None
        r = receipt.Receipt(self.r_business.text(), self.r_address.text(), self.r_url.text(), items,
                            self.r_footer.text())
        self.r_total.setText(f"Total {receipt.clp(r.total)}" if items else "")
        if not items:
            self.r_error.setText("Add products with their quantity and price.")
            return None
        return r

    def _editor(self, widget, *extra):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(widget)
        for label, field in extra:
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(field)
            row.addStretch(1)
            lay.addLayout(row)
        if isinstance(widget, QLineEdit):
            lay.addStretch(1)
        return w

    def _right(self):
        s = self.settings
        w = QWidget(objectName="settings")
        w.setFixedWidth(300)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 16)
        title = QLabel("Print settings")
        title.setStyleSheet("font-weight: 700; font-size: 16px")
        lay.addWidget(title)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)

        self.dither = QComboBox()
        for k, v in imaging.DITHERS.items():
            self.dither.addItem(v, k)
        self.dither.setCurrentIndex(max(0, self.dither.findData(s.value("dither", "atkinson"))))
        self.dark = QSlider(Qt.Horizontal, minimum=1, maximum=5, value=int(s.value("darkness", 3)))
        self.dark_label = QLabel()
        self.bright = QSlider(Qt.Horizontal, minimum=-50, maximum=50, value=int(s.value("brightness", 0)))
        self.contrast = QSlider(Qt.Horizontal, minimum=50, maximum=200, value=int(s.value("contrast", 100)))
        self.pages = QLineEdit(placeholderText="All pages (e.g. 1-2,5)")
        self.rotate = QCheckBox("Rotate wide pictures to fit")
        self.rotate.setChecked(s.value("rotate", "true") == "true")
        self.trim = QCheckBox("Trim white margins of PDF pages")
        self.trim.setChecked(s.value("trim", "true") == "true")
        self.doc_look = QComboBox()
        self.doc_look.addItem("Sharp (text, line art)", "threshold")
        self.doc_look.addItem("Dithered (pictures)", "dither")
        self.doc_look.setCurrentIndex(max(0, self.doc_look.findData(s.value("doc_look", "threshold"))))
        self.copies = QSpinBox(minimum=1, maximum=50, value=1)
        self.dialog_quality = QComboBox()
        self.dialog_quality.addItem("Sharp (text, receipts)", "threshold")
        self.dialog_quality.addItem("Photo (dithered)", "atkinson")
        self.dialog_quality.setCurrentIndex(max(0, self.dialog_quality.findData(
            s.value("dialog_quality", "threshold"))))

        form.addRow("Look", self.doc_look)
        form.addRow("Dithering", self.dither)
        form.addRow(self.dark_label, self.dark)
        form.addRow("Brightness", self.bright)
        form.addRow("Contrast", self.contrast)
        form.addRow("Pages", self.pages)
        form.addRow(self.rotate)
        form.addRow(self.trim)
        form.addRow("Copies", self.copies)
        form.addRow("Jobs from the Windows print dialog", self.dialog_quality)
        lay.addLayout(form)
        self.form = form
        # Rows that only mean something for some modes; hidden elsewhere to keep the pane short.
        photo, doc = {"photo"}, {"document"}
        self.mode_rows = {self.doc_look: doc, self.dither: photo, self.bright: photo, self.contrast: photo,
                          self.rotate: photo, self.pages: doc, self.trim: doc}
        lay.addStretch(1)
        self.length = QLabel()
        lay.addWidget(self.length)
        self.print_btn = QPushButton("Print", objectName="print")
        self.print_btn.clicked.connect(self.print_now)
        lay.addWidget(self.print_btn)
        self.api_label = QLabel()
        self.api_label.setStyleSheet("color: palette(placeholder-text); font-size: 11px")
        self.api_label.setWordWrap(True)
        self.api_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        api = QPushButton("API settings…", flat=True)
        api.clicked.connect(lambda: QApplication.instance().api_dialog())
        lay.addWidget(self.api_label)
        lay.addWidget(api)

        for sig in (self.dither.currentIndexChanged, self.bright.valueChanged,
                    self.contrast.valueChanged, self.pages.textChanged, self.rotate.toggled,
                    self.trim.toggled, self.doc_look.currentIndexChanged):
            sig.connect(self.schedule)
        for sig in (self.dark.valueChanged, self.copies.valueChanged, self.dialog_quality.currentIndexChanged):
            sig.connect(self.save_settings)
        self.dark.valueChanged.connect(self.update_labels)
        self.dark.valueChanged.connect(lambda *_: self.update_printer({}, keep_state=True))
        self.copies.valueChanged.connect(self.update_labels)
        return w

    # -- state --

    def model(self):
        cfg = config.load()
        return lookup(cfg.get("model") or cfg.get("name", ""))

    def energy(self):
        return DARKNESS[self.dark.value() - 1]

    def save_settings(self, *_):
        s = self.settings
        s.setValue("dither", self.dither.currentData())
        s.setValue("darkness", self.dark.value())
        s.setValue("brightness", self.bright.value())
        s.setValue("contrast", self.contrast.value())
        s.setValue("rotate", "true" if self.rotate.isChecked() else "false")
        s.setValue("trim", "true" if self.trim.isChecked() else "false")
        s.setValue("dialog_quality", self.dialog_quality.currentData())
        s.setValue("doc_look", self.doc_look.currentData())
        s.setValue("mode_key", self.mode())
        if hasattr(self, "r_items"):
            s.setValue("receipt_business", self.r_business.text())
            s.setValue("receipt_address", self.r_address.text())
            s.setValue("receipt_url", self.r_url.text())
            s.setValue("receipt_footer", self.r_footer.text())
            s.setValue("receipt_items", json.dumps(self.receipt_rows(), ensure_ascii=False))

    def mode(self):
        it = self.nav.currentItem()
        return it.data(Qt.UserRole) if it else self.order[0]

    def set_mode(self, key):
        self.nav.setCurrentRow(self.order.index(key))

    def mode_changed(self, row):
        key = self.mode()
        self.editors.setCurrentIndex(self.editor_of[key])
        self.editors.setMaximumHeight(280 if key == "receipt" else 200)
        for widget, modes in self.mode_rows.items():
            self.form.setRowVisible(widget, key in modes)
        self.schedule()

    def schedule(self, *_):
        self.save_settings()
        self.debounce.start()

    def update_labels(self, *_):
        self.dark_label.setText(f"Darkness: {DARKNESS_NAMES[self.dark.value() - 1]}")
        n = self.copies.value()
        self.print_btn.setText("Print" if n == 1 else f"Print {n} copies")
        self.print_btn.setEnabled(bool(self.rows))
        self.update_length()

    def update_length(self):
        """Paper and time under the preview; follows copies and darkness (darker prints slower)."""
        m = getattr(self, "_preview_model", None)
        if not self.rows or m is None:
            return
        n = self.copies.value()
        mm = len(self.rows) * 25.4 / m.dpi * n
        secs = api.estimate(len(self.rows), m, n, energy=self.energy())
        self.length.setText(f"About {mm:.0f} mm of paper, {protocol.format_eta(secs)} to print")

    # -- content --

    def file_images(self, kind, width):
        """Source pictures for Photo or Document, cached because PDF rendering is slow.

        Documents print sharp (threshold) unless their Look says dithered; photos are dithered.
        """
        doc = kind == "document"
        try:
            pages = parse_pages(self.pages.text()) if doc else None
        except ValueError:
            pages = None
        sharp = doc and self.doc_look.currentData() == "threshold"
        trim = doc and self.trim.isChecked()
        key = (tuple(id(s) if not isinstance(s, (str, Path)) else str(s) for _, s in self.sources[kind]),
               width, pages, trim, sharp)
        if self._cache.get(kind, (None,))[0] != key:
            out = []
            for label, src in self.sources[kind]:
                try:
                    if not isinstance(src, (str, Path)):
                        out.append((src, sharp))
                    elif convert.kind(src) == "pdf":
                        out += [(im, sharp) for im in pdf_images(src, width, pages, trim)]
                    else:
                        out += [(im, t or sharp) for im, t in convert.to_images(src, width)]
                except Exception as e:
                    QMessageBox.warning(self, APP, f"Can't open {label}:\n{e}")
            self._cache[kind] = (key, out)
        return self._cache[kind][1]

    def items(self, width):
        """[(PIL image, sharp)] for the current mode."""
        mode = self.mode()
        if mode in ("photo", "document"):
            return self.file_images(mode, width)
        if mode == "text":
            t = self.text.toPlainText()
            return [(imaging.text_image(t, width, size=self.text_size.value()), True)] if t.strip() else []
        if mode == "list":
            lines = self.list_items.toPlainText().splitlines()
            if not any(l.strip() for l in lines) and not self.list_title.text().strip():
                return []
            return [(imaging.checklist_image(self.list_title.text(), lines, width), True)]
        if mode == "banner":
            t = self.banner.text().strip()
            return [(imaging.banner_image(t, width), True)] if t else []
        if mode == "qr":
            t = self.qr.text().strip()
            return [(imaging.qr_image(t, width), True)] if t else []
        if mode == "receipt":
            r = self.receipt()
            return [(r.image(width), True)] if r else []
        t = self.barcode.text().strip()
        self.barcode_error.setText("")
        if not t:
            return []
        try:
            return [(imaging.barcode_image(t, width), True)]
        except ValueError as e:
            self.barcode_error.setText(f"Can't make this barcode: {e}")
            return []

    def snapshot(self, method=None):
        """Current image settings. Taken on the UI thread; jobs build rows on the worker thread."""
        return dict(method=method or self.dither.currentData(), rotate=self.rotate.isChecked(),
                    brightness=self.bright.value() / 100, contrast=self.contrast.value() / 100)

    @staticmethod
    def build(items, width, method, rotate, brightness, contrast):
        """Items → (rows, mode)."""
        rows, sharp_only = [], True
        for img, sharp in items:
            sharp_only &= sharp
            if sharp:
                rows += imaging.bw_rows(imaging.gray(img, width, auto_rotate=False), "threshold")
            else:
                rows += imaging.bw_rows(imaging.gray(img, width, rotate, brightness, contrast), method)
        return rows, protocol.MODE_TEXT if sharp_only and items else protocol.MODE_IMAGE

    def render(self):
        m = self.model()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.rows, _ = self.build(self.items(m.width), m.width, **self.snapshot())
        finally:
            QApplication.restoreOverrideCursor()
        for kind, label in self.files_label.items():
            names = [l for l, _ in self.sources[kind]]
            label.setText(", ".join(names) if names else "Nothing added yet.")
        if self.rows:
            self.paper.setPixmap(QPixmap.fromImage(qimage_from_rows(self.rows, m.width)))
            mm = len(self.rows) * 25.4 / m.dpi
            self.caption.setText(f"{m.width} × {len(self.rows)} dots · {m.width * 25.4 / m.dpi:.0f} × {mm:.0f} mm")
            self._preview_model = m
            self.update_length()
        else:
            self.paper.setPixmap(QPixmap())
            self.paper.setText("Preview appears here")
            self.caption.setText("")
            self.length.setText("")
        self.update_labels()

    def add_sources(self, paths=(), images=(), kind=None):
        """Pictures go to Photo, PDFs and text to Document (unless `kind` says where)."""
        first = None
        for p in paths:
            try:
                k = kind or ("photo" if convert.kind(p) == "image" else "document")
            except (OSError, convert.Unsupported):
                k = kind or "document"
            self.sources[k].append((Path(p).name, str(p)))
            first = first or k
        for img in images:
            self.sources[kind or "photo"].append(("Pasted picture", img))
            first = first or kind or "photo"
        if first:
            self.set_mode(first)
        self.schedule()

    def open_files(self):
        kind = self.mode() if self.mode() in ("photo", "document") else None
        filters = {"photo": "Pictures (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.tif *.tiff);;All files (*)",
                   "document": "PDFs and text (*.pdf *.txt *.md);;All files (*)"}
        paths, _ = QFileDialog.getOpenFileNames(self, "Open", "", filters.get(kind, "Images, PDFs, text (*.png "
                                                "*.jpg *.jpeg *.gif *.bmp *.webp *.tif *.tiff *.pdf *.txt *.md);;All files (*)"))
        if paths:
            self.add_sources(paths, kind=kind)

    def paste(self):
        if isinstance(self.focusWidget(), (QLineEdit, QPlainTextEdit)):   # also the receipt table's cells
            self.focusWidget().paste()
            return
        md = QApplication.clipboard().mimeData()
        if md.hasImage():
            self.add_sources(images=[pil_from_qimage(QApplication.clipboard().image())])
        elif md.hasUrls():
            self.add_sources([u.toLocalFile() for u in md.urls() if u.isLocalFile()])
        elif md.hasText():
            self.set_mode("text")
            self.text.setPlainText(md.text())

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasUrls():
            self.add_sources([u.toLocalFile() for u in md.urls() if u.isLocalFile()])
        elif md.hasImage():
            self.add_sources(images=[pil_from_qimage(QImage(md.imageData()))])

    # -- printing --

    def print_now(self):
        if not self.rows:
            return
        mode = self.mode()
        items = list(self.items(self.model().width))
        snapshot = self.snapshot()
        label = MODES[mode][0]
        src = self.sources.get(mode)
        if src:
            label = src[0][0] + (f" +{len(src) - 1}" if len(src) > 1 else "")
        if mode == "receipt":
            label = self.r_total.text().replace("Total", "Receipt")
        if not self.confirm_busy(label):
            return

        def build(width):
            return self.build(items, width, **snapshot)
        self.usage = features.record_use(self.usage, mode)
        self.settings.setValue("usage", json.dumps(self.usage))
        self.fly_to_queue()
        self.worker.print_job(label, build, self.energy(), self.copies.value(), lines=len(self.rows))

    # -- busy printer: ask first, and show the job flying into the queue --

    def active_jobs(self):
        return [j for j in self.jobs.values() if j["state"] in ("waiting", "printing")]

    def job_left(self, j, now=None):
        """Seconds left on a job; a fresh guess for jobs whose size isn't known yet."""
        now = time.monotonic() if now is None else now
        est = j["est"] if j["est"] is not None else protocol.CONNECT_S + protocol.COPY_OVERHEAD_S
        return est if j["t0"] is None else max(0.0, est - (now - j["t0"]))

    def queue_left(self, now=None):
        return sum(self.job_left(j, now) for j in self.active_jobs())

    def confirm_busy(self, label):
        """True to go ahead. When something is already printing (here or in another program), ask."""
        mine = self.active_jobs()
        other = busy.current()
        if other and other.get("pid") == os.getpid():
            other = None
        if not mine and not other:
            return True
        if mine:
            cur = next((j for j in mine if j["state"] == "printing"), mine[0])
            left = self.job_left(cur)
            what = f"“{cur['label']}” is printing: " + (f"about {protocol.format_eta(left)} left." if left
                                                        else "almost done.")
            if len(mine) > 1:
                what += f" {len(mine) - 1} more waiting."
            start = self.queue_left()
        else:
            what = busy.describe(other) + "."
            start = busy.queue_remaining(other)
        return self.ask("The printer is busy", what,
                        f"Add “{label}” to the queue? It should start in about {protocol.format_eta(start)}.",
                        "Add to queue")

    def ask(self, title, text, info, yes):
        box = QMessageBox(QMessageBox.Question, title, text, parent=self)
        box.setInformativeText(info)
        ok = box.addButton(yes, QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(ok)
        box.exec()
        return box.clickedButton() is ok

    def fly_to_queue(self):
        """A paper slip flies from the Print button into the queue, so you see the job go in."""
        root = self.centralWidget()
        a = QPointF(self.print_btn.mapTo(root, self.print_btn.rect().center()))
        b = QPointF(self.queue.mapTo(root, QPoint(self.queue.width() // 2, 14)))
        c = QPointF((a.x() + b.x()) / 2, min(a.y(), b.y()) - 140)       # arc over the preview
        slip = QLabel(root)
        slip.setPixmap(ticket_pixmap(QGuiApplication.palette().accent().color()))
        slip.setAttribute(Qt.WA_TransparentForMouseEvents)
        slip.resize(26, 34)
        slip.move((a - QPointF(13, 17)).toPoint())
        slip.show()
        slip.raise_()
        anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=700,
                                 easingCurve=QEasingCurve.InOutCubic)

        def step(t):
            p = a * (1 - t) ** 2 + c * (2 * (1 - t) * t) + b * t * t
            slip.move(int(p.x()) - 13, int(p.y()) - 17)
        anim.valueChanged.connect(step)
        anim.finished.connect(slip.deleteLater)
        anim.finished.connect(self.flash_newest_job)
        anim.start(QAbstractAnimation.DeleteWhenStopped)
        self._fly = anim

    def flash_newest_job(self):
        it = self.queue.item(0)
        if it is None:
            return
        c = QGuiApplication.palette().accent().color()
        c.setAlpha(70)
        it.setBackground(c)
        QTimer.singleShot(900, lambda: self.queue.row(it) >= 0 and it.setBackground(QBrush()))

    def choose_printer(self):
        d = PrinterDialog(self.worker, self)
        if d.exec() and d.chosen():
            name, addr = d.chosen()
            config.forget()
            m = lookup(name)
            from ..api import BLE_VERIFIED
            ble = not m.use_spp or m.name in BLE_VERIFIED
            config.save(name=name, address=addr, transport="ble" if ble else None)
            self.update_printer({})
            self.schedule()
            self.worker.refresh()

    def update_printer(self, st, keep_state=False):
        cfg = config.load()
        name = st.get("name") or cfg.get("name")
        self.p_name.setText(name or "No printer yet")
        self.pick.setVisible(not name)
        self.p_dark.setText(f"Darkness: {DARKNESS_NAMES[self.dark.value() - 1]}")
        if keep_state:
            return
        if st:
            parts = [st.get("state") or "connected"]
            if st.get("battery") is not None:
                parts.append(f"{st['battery']}% battery")
            self.p_state.setText(" · ".join(parts).capitalize())
        elif name:
            how = cfg.get("port") or ("Bluetooth LE" if cfg.get("transport") == "ble" else "Bluetooth")
            self.p_state.setText(f"{self.model().name} · {how}")
        else:
            self.p_state.setText("Found automatically on first print, or pick one.")

    def job_queued(self, jid, label):
        it = QListWidgetItem()
        self.queue.insertItem(0, it)
        info = getattr(self.worker, "jobs", {}).get(jid, {})
        est = info.get("seconds") if isinstance(info, dict) else None
        self.jobs[jid] = {"label": label, "state": "waiting", "est": est, "t0": None, "pct": 0,
                          "note": "", "item": it, "end": None, "error": ""}
        while self.queue.count() > 30:
            old = self.queue.takeItem(self.queue.count() - 1)
            for k in [k for k, j in self.jobs.items() if j["item"] is old]:
                del self.jobs[k]
        self.refresh_queue()

    def _job(self, jid, **changes):
        j = self.jobs.get(jid)
        if j:
            j.update(changes)
            self.refresh_queue()

    def job_started(self, jid):
        self._job(jid, state="printing", t0=time.monotonic(), note="connecting…")

    def job_estimate(self, jid, seconds):
        self._job(jid, est=seconds, t0=time.monotonic(), note="")      # countdown restarts once laid out

    def job_progress(self, jid, pct):
        self._job(jid, pct=pct)

    def job_blocked(self, jid, text):
        self._job(jid, note=text)

    def job_finished(self, jid, err):
        self._job(jid, state="failed" if err else "done", error=err, end=time.strftime("%H:%M"), note="")

    def refresh_queue(self):
        now = time.monotonic()
        ahead = 0.0
        for j in sorted(self.jobs.values(), key=lambda j: -self.queue.row(j["item"])):   # oldest first
            if j["state"] == "waiting":
                status = j["note"] or f"waiting · starts in about {protocol.format_eta(ahead)}"
            elif j["state"] == "printing":
                left = self.job_left(j, now)
                status = j["note"] or (f"printing {j['pct']}% · about {protocol.format_eta(left)} left"
                                       if left else f"printing {j['pct']}% · finishing")
            elif j["state"] == "done":
                status = f"printed at {j['end']}"
            else:
                status = f"failed: {j['error']}"
            if j["state"] in ("waiting", "printing"):
                ahead += self.job_left(j, now)
            j["item"].setText(f"{j['label']}\n{status}")
        n = len(self.active_jobs())
        self.queue_summary.setText(f"{n} · done in about {protocol.format_eta(ahead)}" if n else "")

    def showEvent(self, e):
        super().showEvent(e)
        self.restyle()

    def restyle(self, *_):
        # Windows sends the scheme change before Qt has the new palette; let it settle first.
        QTimer.singleShot(150, self._restyle)

    def _restyle(self):
        # palette(...) in stylesheets is resolved once, when the sheet is set, so on a light/dark
        # switch rebuild the style (fresh system palette) and re-set every sheet that uses it.
        app = QApplication.instance()
        app.setStyleSheet("")
        app.setStyle("windows11")
        app.setStyleSheet(STYLE)
        for w in app.allWidgets():
            ss = w.styleSheet()
            if ss:
                w.setStyleSheet("")
                w.setStyleSheet(ss)
        fluent_window(self)
        self.print_btn.setStyleSheet(f"QPushButton#print:enabled {{ color: {accent_text()}; }}")
        # Glyph icons are drawn in the text colour, which changes with light/dark.
        self.gear.setIcon(glyph_icon(GLYPH_SETTINGS, 18))
        self.p_icon.setPixmap(glyph_icon(GLYPH_PRINTER, 18).pixmap(18, 18))
        for i in range(self.nav.count()):
            it = self.nav.item(i)
            it.setIcon(glyph_icon(MODES[it.data(Qt.UserRole)][1], 18))

    def closeEvent(self, e):
        # Keep running in the tray so the print dialog and hotkey keep working.
        e.ignore()
        self.hide()
        if not self.settings.value("told_tray"):
            self.settings.setValue("told_tray", 1)
            QApplication.instance().tray.showMessage(
                APP, "Still running in the tray, so “iPreent” keeps working in print dialogs.", icon(), 4000)


# ---- tray + app ------------------------------------------------------------------------------

def local_ip():
    """This PC's address on the local network (the one other devices would use)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.connect(("192.168.0.1", 9))     # no packet is sent; just picks the LAN interface
            return sk.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def exe_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pyw}" -m ipreent.desktop --tray'


def autostart(enable=None):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if enable is True:
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, exe_command())
        elif enable is False:
            try:
                winreg.DeleteValue(k, APP)
            except OSError:
                pass
        try:
            winreg.QueryValueEx(k, APP)
            return True
        except OSError:
            return False


class App(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.setApplicationName(APP)
        self.setQuitOnLastWindowClosed(False)
        self.setWindowIcon(icon())
        self.setStyle("windows11")
        f = QFont("Segoe UI Variable Text")
        f.setPointSizeF(9.5)
        self.setFont(f)
        self.setStyleSheet(STYLE)
        self.settings = QSettings(APP, APP)
        self.worker = Worker()
        self.win = MainWindow(self.worker, self.settings)
        self.styleHints().colorSchemeChanged.connect(self.win.restyle)

        w = self.worker
        w.queued.connect(self.win.job_queued)
        w.started.connect(self.win.job_started)
        w.progress.connect(self.win.job_progress)
        w.estimate.connect(self.win.job_estimate)
        w.blocked.connect(self.win.job_blocked)
        w.finished.connect(self.job_finished)
        w.status.connect(self.status)

        self.tray = QSystemTrayIcon(icon(), self)
        self.tray.setToolTip(APP)
        menu = QMenu()
        self.status_action = menu.addAction("Printer: not checked yet")
        self.status_action.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Print clipboard\tCtrl+Alt+P", self.print_clipboard)
        menu.addAction("Print file…", self.print_file_dialog)
        menu.addAction("Quick note…", self.quick_note)
        menu.addAction("Feed paper", self.worker.feed)
        menu.addSeparator()
        self.dialog_action = menu.addAction("Add “iPreent” to print dialogs", self.toggle_printer)
        self.autostart_action = QAction("Start with Windows", menu, checkable=True)
        self.autostart_action.setChecked(autostart())
        self.autostart_action.toggled.connect(lambda on: autostart(on))
        menu.addAction(self.autostart_action)
        menu.addSeparator()
        self.api_action = QAction("HTTP API", menu, checkable=True)
        self.api_action.toggled.connect(self.toggle_api)
        menu.addAction(self.api_action)
        menu.addAction("API settings…", self.api_dialog)
        menu.addAction(f"Open {APP}", self.show_window)
        menu.addAction("Quit", self.quit)
        menu.aboutToShow.connect(self.refresh_menu)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show_window() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self._menu = menu

        self.hotkey = HotkeyFilter(self.print_clipboard)
        self.installNativeEventFilter(self.hotkey)

        self.spool_jobs = set()
        for old in spool.leftover_jobs():
            if time.time() - old.stat().st_mtime > 3600:
                old.unlink(missing_ok=True)
            else:
                self.print_spooled(old)
        self.spool_timer = QTimer(self, interval=1000, timeout=self.poll_spool)
        self.spool_timer.start()
        self._printer_installed = None

        if not self.settings.value("api_token"):
            self.settings.setValue("api_token", secrets.token_urlsafe(18))
        self.server = Server(self.worker, self.api_print, self.api_defaults)
        self.start_api()

    def show_window(self):
        self.win.showNormal()
        self.win.raise_()
        self.win.activateWindow()

    def refresh_menu(self):
        self.api_action.blockSignals(True)
        self.api_action.setChecked(self.api_settings()[0])
        self.api_action.blockSignals(False)
        if self._printer_installed is None:
            self._printer_installed = spool.installed()
        self.dialog_action.setText("Remove “iPreent” from print dialogs" if self._printer_installed
                                   else "Add “iPreent” to print dialogs")

    def toggle_printer(self):
        on = spool.installed()
        ok = spool.uninstall() if on else spool.install()
        self._printer_installed = spool.installed()
        if not ok:
            self.tray.showMessage(APP, "That didn't work (admin permission is needed once).",
                                  QSystemTrayIcon.Warning, 5000)
        elif not on:
            self.tray.showMessage(APP, "Done. Choose “iPreent” in any app's Print dialog. "
                                  "Keep this app running in the tray.", icon(), 6000)

    def job_finished(self, jid, err):
        self.win.job_finished(jid, err)
        if err:
            self.tray.showMessage(APP, f"Print failed: {err}", QSystemTrayIcon.Warning, 5000)

    def status(self, st):
        self.win.update_printer(st)
        parts = [st.get("name") or st.get("model"), st.get("state") or "connected"]
        if st.get("battery") is not None:
            parts.append(f"{st['battery']}%")
        self.status_action.setText(" · ".join(p for p in parts if p))

    # -- quick actions --

    def print_items(self, label, make_items, method=None):
        snap = self.win.snapshot(method)
        self.worker.print_job(label, lambda w: MainWindow.build(make_items(w), w, **snap), self.win.energy())

    def print_clipboard(self):
        cb = self.clipboard()
        md = cb.mimeData()
        if md.hasImage():
            img = pil_from_qimage(cb.image())
            self.print_items("Clipboard picture", lambda w: [(img, False)])
        elif md.hasUrls():
            for u in md.urls():
                if u.isLocalFile():
                    self.print_path(u.toLocalFile())
        elif md.hasText() and md.text().strip():
            text = md.text()
            self.print_items("Clipboard text", lambda w: [(imaging.text_image(text, w), True)])
        else:
            self.tray.showMessage(APP, "The clipboard is empty.", icon(), 3000)

    def print_path(self, path, on_done=None, method=None, trim=None):
        trim = self.win.trim.isChecked() if trim is None else trim

        def items(width):
            if convert.kind(path) == "pdf":
                return [(im, False) for im in pdf_images(path, width, trim=trim)]
            return list(convert.to_images(path, width))

        snap = self.win.snapshot(method)
        self.worker.print_job(Path(path).name, lambda w: MainWindow.build(items(w), w, **snap),
                              self.win.energy(), on_done=on_done)

    def print_file_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(None, "Print file", "")
        for p in paths:
            self.print_path(p)

    def quick_note(self):
        text, ok = QInputDialog.getMultiLineText(None, "Quick note", "Text to print:")
        if ok and text.strip():
            self.print_items("Quick note", lambda w: [(imaging.text_image(text, w), True)])

    # -- print dialog bridge --

    def poll_spool(self):
        job = spool.take_job()
        if job:
            self.tray.showMessage(APP, "Printing from the print dialog…", icon(), 2000)
            self.print_spooled(job)

    def print_spooled(self, path):
        if path in self.spool_jobs:
            return
        self.spool_jobs.add(path)

        def done():
            path.unlink(missing_ok=True)
            self.spool_jobs.discard(path)
        self.print_path(str(path), on_done=done, method=self.win.dialog_quality.currentData(), trim=True)

    # -- HTTP API --

    def api_defaults(self):
        s = QSettings(APP, APP)    # own instance: called from server threads
        return {"dither": s.value("dither", "atkinson"), "darkness": int(s.value("darkness", 3)),
                "brightness": int(s.value("brightness", 0)), "contrast": int(s.value("contrast", 100)),
                "trim": s.value("trim", "true") == "true", "rotate": s.value("rotate", "true") == "true"}

    def api_print(self, label, make_items, o):
        snap = dict(method=o["method"], rotate=o["rotate"], brightness=o["brightness"], contrast=o["contrast"])
        return self.worker.print_job(label, lambda w: MainWindow.build(make_items(w), w, **snap),
                                     DARKNESS[o["darkness"] - 1], o["copies"])

    def api_settings(self):
        s = self.settings
        return (s.value("api_enabled", "false") == "true", int(s.value("api_port", 8787)),
                s.value("api_lan", "false") == "true", s.value("api_token"))

    def toggle_api(self, on):
        self.settings.setValue("api_enabled", "true" if on else "false")
        self.start_api()
        if on and not self.server.running:
            self.tray.showMessage(APP, f"The API couldn't start: {self.server.error}", QSystemTrayIcon.Warning, 5000)

    def start_api(self):
        on, port, lan, token = self.api_settings()
        self.server.stop()
        if on:
            self.server.start("0.0.0.0" if lan else "127.0.0.1", port, token)
        self.win.api_label.setText(self.api_summary())

    def api_summary(self):
        on, port, lan, _ = self.api_settings()
        if not on:
            return "API off"
        if not self.server.running:
            return f"API not running ({self.server.error})"
        host = local_ip() if lan else "127.0.0.1"
        return f"API on http://{host}:{port}" + (" (token needed)" if lan else "")

    def api_dialog(self):
        on, port, lan, token = self.api_settings()
        d = QDialog(self.win if self.win.isVisible() else None)
        d.setWindowTitle("API settings")
        enabled = QCheckBox("Accept print jobs from other programs", checked=on)
        port_box = QSpinBox(minimum=1024, maximum=65535, value=port)
        lan_box = QCheckBox("Allow other devices on my network (needs the token)", checked=lan)
        tok = QLineEdit(token, readOnly=True)
        new = QPushButton("New token")
        new.clicked.connect(lambda: tok.setText(secrets.token_urlsafe(18)))
        help_ = QLabel()
        help_.setTextInteractionFlags(Qt.TextSelectableByMouse)
        help_.setStyleSheet("font-family: Consolas, monospace; font-size: 11px")

        def update_help():
            host = local_ip() if lan_box.isChecked() else "127.0.0.1"
            auth = f' -H "Authorization: Bearer {tok.text()}"' if lan_box.isChecked() else ""
            url = f"http://{host}:{port_box.value()}"
            help_.setText(f'curl{auth} -X POST {url}/text -d "Hello"\n'
                          f'curl{auth} -X POST {url}/print --data-binary @photo.jpg\n'
                          "All endpoints: README > Windows app > API")
        for sig in (lan_box.toggled, port_box.valueChanged, tok.textChanged):
            sig.connect(update_help)
        update_help()
        form = QFormLayout(d)
        form.addRow(enabled)
        form.addRow("Port", port_box)
        form.addRow(lan_box)
        row = QHBoxLayout()
        row.addWidget(tok, 1)
        row.addWidget(new)
        form.addRow("Token", row)
        form.addRow(help_)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(d.accept)
        buttons.rejected.connect(d.reject)
        form.addRow(buttons)
        if d.exec():
            s = self.settings
            s.setValue("api_enabled", "true" if enabled.isChecked() else "false")
            s.setValue("api_port", port_box.value())
            s.setValue("api_lan", "true" if lan_box.isChecked() else "false")
            s.setValue("api_token", tok.text())
            self.start_api()
            if enabled.isChecked() and not self.server.running:
                QMessageBox.warning(None, APP, f"The API couldn't start: {self.server.error}")

    # -- other instances hand their arguments to us --

    def handle_args(self, args):
        tray_only = "--tray" in args
        files = [a for a in args if not a.startswith("--") and Path(a).exists()]
        if files:
            self.win.add_sources(files)
        if files or not tray_only:
            self.show_window()


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("iPreent.Desktop")

    app = App(sys.argv[:1])
    sock = QLocalSocket()
    sock.connectToServer("ipreent-desktop")
    if sock.waitForConnected(300):           # already running: pass the arguments on
        sock.write("\0".join(args or ["--show"]).encode())
        sock.waitForBytesWritten(1000)
        return 0
    server = QLocalServer()
    QLocalServer.removeServer("ipreent-desktop")
    server.listen("ipreent-desktop")

    def incoming():
        c = server.nextPendingConnection()

        def read():
            app.handle_args(bytes(c.readAll()).decode().split("\0"))
        c.readyRead.connect(read)
    server.newConnection.connect(incoming)
    app.handle_args(args)
    return app.exec()

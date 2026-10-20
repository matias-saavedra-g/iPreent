"""iPreent for Windows: main window, tray menu, global hotkey and the print-dialog bridge."""
import ctypes
import ctypes.wintypes
import io
import secrets
import socket
import sys
import time
import winreg
from pathlib import Path

from PIL import Image
from PySide6.QtCore import (QAbstractNativeEventFilter, QBuffer, QIODevice, QSettings, Qt, QTimer)
from PySide6.QtGui import QAction, QFont, QGuiApplication, QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSlider,
                               QSpinBox, QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from .. import config, convert, imaging, protocol
from ..cli import ENERGY_PRESETS
from ..models import lookup
from . import spool
from .server import Server
from .worker import Worker

APP = "iPreent"
HERE = Path(__file__).parent
DARKNESS = list(ENERGY_PRESETS.values())          # slider 1..5
DARKNESS_NAMES = ["Lightest", "Lighter", "Normal", "Darker", "Darkest"]
MODES = ["Image or PDF", "Text", "Checklist", "Banner", "QR code", "Barcode"]
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
        self.sources = []            # [(label, path or PIL image)]
        self._cache_key, self._cache = None, []
        self.rows = []
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

        self.nav.setCurrentRow(int(settings.value("mode", 0)))
        self.update_printer({})
        self.schedule()

    # -- layout --

    def _section(self, text):
        lab = QLabel(text.upper())
        lab.setObjectName("section")
        return lab

    def _left(self):
        w = QWidget(objectName="side")
        w.setFixedWidth(260)
        lay = QVBoxLayout(w)
        card = QFrame(objectName="card")
        cl = QVBoxLayout(card)
        self.p_name = QLabel()
        self.p_name.setStyleSheet("font-weight: 600; font-size: 14px")
        self.p_state = QLabel()
        self.p_state.setWordWrap(True)
        row = QHBoxLayout()
        change = QPushButton("Change printer")
        change.clicked.connect(self.choose_printer)
        check = QPushButton("Check")
        check.clicked.connect(self.worker.refresh)
        row.addWidget(change)
        row.addWidget(check)
        cl.addWidget(self.p_name)
        cl.addWidget(self.p_state)
        cl.addLayout(row)
        lay.addWidget(card)

        lay.addWidget(self._section("Create"))
        self.nav = QListWidget(objectName="nav")
        self.nav.addItems(MODES)
        self.nav.setFixedHeight(len(MODES) * 38 + 6)
        self.nav.currentRowChanged.connect(self.mode_changed)
        lay.addWidget(self.nav)

        lay.addWidget(self._section("Queue"))
        self.queue = QListWidget(objectName="queue")
        lay.addWidget(self.queue, 1)
        self.queue_items = {}
        return w

    def _center(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 16, 16, 8)
        self.editors = QStackedWidget()

        # Image or PDF
        files = QWidget()
        fl = QVBoxLayout(files)
        fl.setContentsMargins(0, 0, 0, 0)
        self.drop = QLabel("Drop images, PDFs or text files here, paste with Ctrl+V,\n"
                           "or print from any app with File › Print › iPreent", objectName="drop")
        self.drop.setAlignment(Qt.AlignCenter)
        fr = QHBoxLayout()
        self.files_label = QLabel()
        self.files_label.setWordWrap(True)
        openb = QPushButton("Open…")
        openb.clicked.connect(self.open_files)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: (self.sources.clear(), self.schedule()))
        fr.addWidget(self.files_label, 1)
        fr.addWidget(openb)
        fr.addWidget(clear)
        fl.addWidget(self.drop)
        fl.addLayout(fr)
        self.editors.addWidget(files)

        # Text
        self.text = QPlainTextEdit(placeholderText="Type something to print…")
        self.text_size = QSpinBox(minimum=12, maximum=120, value=28, suffix=" px")
        self.editors.addWidget(self._editor(self.text, ("Size", self.text_size)))

        # Checklist
        self.list_title = QLineEdit(placeholderText="Title (optional)")
        self.list_items = QPlainTextEdit(placeholderText="One item per line")
        cw = QWidget()
        cl = QVBoxLayout(cw)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.list_title)
        cl.addWidget(self.list_items)
        self.editors.addWidget(cw)

        # Banner, QR
        self.banner = QLineEdit(placeholderText="Banner text (prints along the paper)")
        self.qr = QLineEdit(placeholderText="Link or text for the QR code")
        self.editors.addWidget(self._editor(self.banner))
        self.editors.addWidget(self._editor(self.qr))

        # Barcode
        self.barcode = QLineEdit(placeholderText="Product code, order number… (Code 128)")
        self.barcode_error = QLabel()
        self.barcode_error.setStyleSheet("color: palette(placeholder-text)")
        bw = self._editor(self.barcode)
        bw.layout().insertWidget(1, self.barcode_error)
        self.editors.addWidget(bw)
        self.barcode.textChanged.connect(self.schedule)
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
        self.copies = QSpinBox(minimum=1, maximum=50, value=1)
        self.dialog_quality = QComboBox()
        self.dialog_quality.addItem("Sharp (text, receipts)", "threshold")
        self.dialog_quality.addItem("Photo (dithered)", "atkinson")
        self.dialog_quality.setCurrentIndex(max(0, self.dialog_quality.findData(
            s.value("dialog_quality", "threshold"))))

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
                    self.trim.toggled):
            sig.connect(self.schedule)
        for sig in (self.dark.valueChanged, self.copies.valueChanged, self.dialog_quality.currentIndexChanged):
            sig.connect(self.save_settings)
        self.dark.valueChanged.connect(self.update_labels)
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
        s.setValue("mode", self.nav.currentRow())

    def mode_changed(self, row):
        self.editors.setCurrentIndex(row)
        self.schedule()

    def schedule(self, *_):
        self.save_settings()
        self.debounce.start()

    def update_labels(self, *_):
        self.dark_label.setText(f"Darkness: {DARKNESS_NAMES[self.dark.value() - 1]}")
        n = self.copies.value()
        self.print_btn.setText("Print" if n == 1 else f"Print {n} copies")
        self.print_btn.setEnabled(bool(self.rows))

    # -- content --

    def file_images(self, width):
        """Source pictures for the file mode, cached because PDF rendering is slow."""
        try:
            pages = parse_pages(self.pages.text())
        except ValueError:
            pages = None
        key = (tuple(id(s) if not isinstance(s, (str, Path)) else str(s) for _, s in self.sources),
               width, pages, self.trim.isChecked())
        if key != self._cache_key:
            out = []
            for label, src in self.sources:
                try:
                    if not isinstance(src, (str, Path)):
                        out.append((src, False))
                    elif convert.kind(src) == "pdf":
                        out += [(im, False) for im in pdf_images(src, width, pages, self.trim.isChecked())]
                    else:
                        out += list(convert.to_images(src, width))
                except Exception as e:
                    QMessageBox.warning(self, APP, f"Can't open {label}:\n{e}")
            self._cache_key, self._cache = key, out
        return self._cache

    def items(self, width):
        """[(PIL image, sharp)] for the current mode."""
        mode = self.nav.currentRow()
        if mode == 0:
            return self.file_images(width)
        if mode == 1:
            t = self.text.toPlainText()
            return [(imaging.text_image(t, width, size=self.text_size.value()), True)] if t.strip() else []
        if mode == 2:
            lines = self.list_items.toPlainText().splitlines()
            if not any(l.strip() for l in lines) and not self.list_title.text().strip():
                return []
            return [(imaging.checklist_image(self.list_title.text(), lines, width), True)]
        if mode == 3:
            t = self.banner.text().strip()
            return [(imaging.banner_image(t, width), True)] if t else []
        if mode == 4:
            t = self.qr.text().strip()
            return [(imaging.qr_image(t, width), True)] if t else []
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
        names = [l for l, _ in self.sources]
        self.files_label.setText(", ".join(names) if names else "Nothing added yet.")
        if self.rows:
            self.paper.setPixmap(QPixmap.fromImage(qimage_from_rows(self.rows, m.width)))
            mm = len(self.rows) * 25.4 / m.dpi
            self.caption.setText(f"{m.width} × {len(self.rows)} dots · {m.width * 25.4 / m.dpi:.0f} × {mm:.0f} mm")
            self.length.setText(f"About {mm * self.copies.value():.0f} mm of paper")
        else:
            self.paper.setPixmap(QPixmap())
            self.paper.setText("Preview appears here")
            self.caption.setText("")
            self.length.setText("")
        self.update_labels()

    def add_sources(self, paths=(), images=()):
        for p in paths:
            self.sources.append((Path(p).name, str(p)))
        for img in images:
            self.sources.append(("Pasted picture", img))
        self.nav.setCurrentRow(0)
        self.schedule()

    def open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Open", "", "Images, PDFs, text (*.png *.jpg *.jpeg "
                                                "*.gif *.bmp *.webp *.tif *.tiff *.pdf *.txt *.md);;All files (*)")
        if paths:
            self.add_sources(paths)

    def paste(self):
        if self.focusWidget() in (self.text, self.list_items, self.list_title, self.banner, self.qr, self.barcode, self.pages):
            self.focusWidget().paste()
            return
        md = QApplication.clipboard().mimeData()
        if md.hasImage():
            self.add_sources(images=[pil_from_qimage(QApplication.clipboard().image())])
        elif md.hasUrls():
            self.add_sources([u.toLocalFile() for u in md.urls() if u.isLocalFile()])
        elif md.hasText():
            self.nav.setCurrentRow(1)
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
        items = list(self.items(self.model().width))
        snapshot = self.snapshot()
        label = MODES[self.nav.currentRow()]
        if self.nav.currentRow() == 0 and self.sources:
            label = self.sources[0][0] + (f" +{len(self.sources) - 1}" if len(self.sources) > 1 else "")

        def build(width):
            return self.build(items, width, **snapshot)
        self.worker.print_job(label, build, self.energy(), self.copies.value())

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

    def update_printer(self, st):
        cfg = config.load()
        name = st.get("name") or cfg.get("name")
        self.p_name.setText(name or "No printer yet")
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
        it = QListWidgetItem(f"{label} · waiting")
        it.setData(Qt.UserRole, label)
        self.queue.insertItem(0, it)
        self.queue_items[jid] = it
        while self.queue.count() > 30:
            self.queue.takeItem(self.queue.count() - 1)

    def job_state(self, jid, text):
        it = self.queue_items.get(jid)
        if it:
            it.setText(f"{it.data(Qt.UserRole)} · {text}")

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
        w.started.connect(lambda j: self.win.job_state(j, "connecting…"))
        w.progress.connect(lambda j, p: self.win.job_state(j, f"sending {p}%"))
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
        self.win.job_state(jid, "failed: " + err if err else "printed")
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

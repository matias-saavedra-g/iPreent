"""Build the portable Windows app: dist/iPreent.exe (one file, no install needed).

    pip install -e .[desktop] pyinstaller
    python tools/build_windows.py
"""
import sys
from pathlib import Path

import PyInstaller.__main__
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "windows"


def make_ico():
    """Render the brand SVGs to a multi-size .ico (small sizes use the simplified icon)."""
    QGuiApplication(sys.argv[:1])
    frames = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        svg = "icon-small.svg" if size <= 32 else "icon.svg"
        img = QImage(size, size, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        QSvgRenderer(str(ROOT / "assets" / "brand" / svg)).render(p)
        p.end()
        path = BUILD / f"icon-{size}.png"
        img.save(str(path))
        frames.append(Image.open(path))
    ico = BUILD / "iPreent.ico"
    frames[-1].save(ico, sizes=[f.size for f in frames], append_images=frames[:-1])
    return ico


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    ico = make_ico()
    entry = BUILD / "launch.py"
    entry.write_text("import sys\nfrom ipreent.desktop.app import main\nsys.exit(main())\n")
    PyInstaller.__main__.run([
        str(entry), "--name", "iPreent", "--onefile", "--console" if "--debug" in sys.argv else "--windowed", "--noconfirm",
        "--icon", str(ico), "--paths", str(ROOT), "--collect-submodules", "ipreent",
        "--distpath", str(ROOT / "dist"), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
        "--add-data", f"{ROOT / 'ipreent' / 'models.json'}{';'}ipreent",
        "--add-data", f"{ROOT / 'ipreent' / 'desktop' / 'icons'}{';'}ipreent/desktop/icons",
        "--collect-submodules", "bleak", "--collect-submodules", "winrt",
        # Qt modules the app doesn't use: keeps the exe smaller.
        *[a for m in ("QtWebEngineCore", "QtWebEngineWidgets", "QtQuick", "QtQml", "Qt3DCore",
                      "QtMultimedia", "QtCharts", "QtDataVisualization", "QtPdf")
          for a in ("--exclude-module", f"PySide6.{m}")],
    ])


if __name__ == "__main__":
    main()

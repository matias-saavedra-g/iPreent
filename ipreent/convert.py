"""Turn any supported file into PIL images ready for imaging.image_rows."""
from pathlib import Path

from PIL import Image

from . import imaging
from .i18n import tr

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ico"}
TEXT_EXT = {".txt", ".md", ".log", ".csv", ".json", ".py", ".ini", ".cfg", ".yaml", ".yml"}


class Unsupported(Exception):
    pass


def kind(path):
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in TEXT_EXT:
        return "text"
    # Unknown extension: sniff it.
    try:
        Image.open(path).verify()
        return "image"
    except Exception:
        pass
    head = Path(path).read_bytes()[:4096]
    if head.startswith(b"%PDF"):
        return "pdf"
    try:
        head.decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        raise Unsupported(tr("don't know how to print {0}", path))


def pdf_pages(path, width, pages=None):
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise Unsupported(tr("PDF support needs: pip install pypdfium2"))
    doc = pdfium.PdfDocument(str(path))
    for i in range(len(doc)):
        if pages and (i + 1) not in pages:
            continue
        page = doc[i]
        scale = width / page.get_width()
        yield page.render(scale=scale * 2).to_pil()   # 2x then downsample for crisp text


def to_images(path, width, font_size=28, pages=None):
    """Yield (image, is_text) for each printable piece of the file."""
    k = kind(path)
    if k == "image":
        img = Image.open(path)
        n = getattr(img, "n_frames", 1)
        if n > 1 and Path(path).suffix.lower() in (".tif", ".tiff"):
            for i in range(n):
                img.seek(i)
                yield img.copy(), False
        else:
            yield img, False
    elif k == "pdf":
        for page in pdf_pages(path, width, pages):
            yield page, False
    else:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        yield imaging.text_image(text, width, size=font_size), True

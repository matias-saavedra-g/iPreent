"""iPreent: an offline, account-free driver for "iPrint"/cat-style thermal mini printers."""

__version__ = "0.8.0"

from .api import (PrinterNotFound, Target, connect, discover, print_file, print_image,  # noqa: E402,F401
                  print_text, status)

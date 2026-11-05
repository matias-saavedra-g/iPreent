# Changelog

Each `## vX.Y.Z` section becomes the notes of that GitHub Release.

## Unreleased
**See that it's printing, and don't print twice by accident** (all versions): pressing Print sends a paper slip
flying into the queue, the queue counts down the time left, and pressing Print again while something is printing
asks before adding it to the queue. Print times start from the printer's 40 mm/s and learn your printer's real
speed from each print. The command line asks `[Y/n]` (`-y` / `--no-wait` for scripts), has `ipreent queue`, and
waits for the Windows app instead of failing to connect.

**New home screen on Android**: three tabs (Create, Queue, History) instead of seven squeezed ones. Create shows
every tool at once, the most used ones biggest; Photo and Document are now separate tools (documents print sharp).
The Windows app gets the same Photo/Document split and orders its modes the same way. Plain `ipreent` now shows an
overview with the most used commands.

**Printer settings are easier to find**: the printer button has a gear and opens a settings sheet (Android) or
menu (Windows card) with darkness, status and battery, find/change and forget. CLI: `ipreent settings`.

## v0.4.1
The Android app is now signed with the permanent iPreent release key, so from this version on each new APK
installs over the previous one and keeps your settings, queue and history.

**Downloads**
- `iPreent-v0.4.1.apk`: Android app (Android 8 or newer). **One last time**, uninstall any iPreent already on
  the phone (including v0.4.0, which was signed with a temporary key) before installing this one.
- `iPreent-v0.4.1-portable.exe`: Windows app. One file, no install, no Python.
- `ipreent-cli-v0.4.1.zip`: command line for Windows, Linux and macOS. Needs Python 3.10+; see `INSTALL.txt` inside.

No other changes from v0.4.0.

## v0.4.0
First published release.

**Downloads**
- `iPreent-v0.4.0.apk`: Android app (Android 8 or newer). If an older iPreent build is installed, uninstall it
  first (it was signed with a different key).
- `iPreent-v0.4.0-portable.exe`: Windows app. One file, no install, no Python.
- `ipreent-cli-v0.4.0.zip`: command line for Windows, Linux and macOS. Needs Python 3.10+; see `INSTALL.txt` inside.

**New: receipts (BOLETA)** in all versions (CLI, Windows app, HTTP API `POST /receipt`, Android):
business name, address and website, products with quantity and price, item count, total in Chilean pesos
(`$12.990`) and a Code 128 barcode. The receipt number is the print date and time, so nothing is stored or synced
between devices. It's a printout, not an SII tax document.

**Already in the apps:** photos and PDFs with dithering, text, checklist, banner, QR and barcode; print queue and
history (Android); share sheet and Android print service; Windows tray, Ctrl+Alt+P clipboard printing,
"Print from any app" printer, and a local HTTP API.

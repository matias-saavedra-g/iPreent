# Changelog

Each `## vX.Y.Z` section becomes the notes of that GitHub Release.

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

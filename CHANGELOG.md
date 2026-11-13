# Changelog

Each `## vX.Y.Z` section becomes the notes of that GitHub Release.

## Unreleased
**Android app in Spanish.** Every screen, message, template name and example text now comes in Spanish, and the app
follows the system language (Spanish → Spanish, anything else → English). The debug settings (tap the printer's
name 7 times) have a new **Language** setting to force English or Spanish while testing. The Windows app and the
command line are still English only.

## v0.7.0
**Downloads**
- `iPreent-v0.7.0.apk`: Android app (Android 8+). Installs over v0.6.0. Also available through Obtainium (see README).
- `iPreent-v0.7.0-portable.exe`: Windows app. One file, no install, no Python.
- `ipreent-cli-v0.7.0.zip`: command line for Windows, Linux and macOS. Needs Python 3.10+; see `INSTALL.txt`.

**Christmas and holiday templates** (all versions): 17 new designs. Christmas: a tree, a gift tag with holly, an
ornament with a name, a letter to the Viejito Pascuero (a wish list that grows), a snowflake frame, a countdown
with candy canes, a stocking and a wreath. Other holidays celebrated in Chile: New Year, Fiestas Patrias (kite,
flag and bunting), Halloween, Valentine's, Easter, Mother's, Father's, Children's and Teachers' Day. No
Thanksgiving. Templates in season come first in the Android and Windows galleries, with their chip first too
(Christmas from 1 November to 26 December). Your own SVGs can have a season too (`ip:season`, docs/TEMPLATES.md).
On Windows the category chips now scroll sideways, so the window can still be made narrow.

**Print times assume 10 mm/s.** Timing real prints wasn't reliable, so estimates no longer learn from them: they
use the printer's slowest nominal speed, 10 mm/s, at every darkness, so a queued print is never promised too
early. Prints are still timed and logged, only to check later (`ipreent bench` still measures the speed).
**Debug settings** change the speed the estimates use, only to test another figure:
- Android: tap the printer's name in the printer sheet 7 times.
- Windows: hold Shift while opening the printer menu → *Debug settings…*.
- Command line: `ipreent settings paper-speed 12` (`reset` goes back to 10). Shared with the Windows app.

## v0.6.0
**Downloads**
- `iPreent-v0.6.0.apk`: Android app (Android 8+). Installs over v0.5.1. Also available through Obtainium (see README).
- `iPreent-v0.6.0-portable.exe`: Windows app. One file, no install, no Python.
- `ipreent-cli-v0.6.0.zip`: command line for Windows, Linux and macOS. Needs Python 3.10+; see `INSTALL.txt`.

**Templates** (all versions): 20 cute designs to fill in with your own text and print: hearts, a love letter, frames
(scalloped, starry, ribbon, cloud, speech bubble), to-do, shopping and "things I love" lists, a sticky note, a
reminder, a sunshine note, birthday, thank-you, confetti and gift-tag cards, a jar label and a name tag. Text shrinks
to fit the design; lists, frames and notes grow longer when you write more. Two bundled fonts (Fredoka, Pacifico) so
they look the same everywhere. Your own SVG files work too (docs/TEMPLATES.md shows how to add text boxes).
- Android: Create › Templates: category chips, a gallery of previews, then the text boxes over the exact print
  preview. *Your own SVG* adds a file to Mine.
- Windows: Templates mode with chips, a strip of previews and the text boxes; *Add SVG…* or drop an `.svg` on the
  window. HTTP API: `GET /templates`, `POST /template`.
- Command line: `ipreent template` lists them, `ipreent template big-heart "Te quiero"` prints one, `--set`,
  `--fields`, `--preview`.
- The command line now needs Python 3.10 or newer (it already said so in INSTALL.txt) and installs `resvg_py`.

**Downloads**
- `iPreent-v0.5.1.apk`: Android app (Android 8+). Installs over v0.5.0. Also available through Obtainium (see README).
- `iPreent-v0.5.1-portable.exe`: Windows app. One file, no install, no Python.
- `ipreent-cli-v0.5.1.zip`: command line for Windows, Linux and macOS. Needs Python 3.10+; see `INSTALL.txt`.

**Print times that match the printer.** Estimates started at 40 mm/s (the listing's "40 ppm"), which was far too
fast. They now start from the nominal 15 mm/s at the lightest darkness down to 10 mm/s at the darkest, since a
darker print heats each line for longer. Every app learns a separate speed for each darkness level from your own prints, and
levels you haven't printed at are worked out from the ones you have. Speeds learnt by earlier versions mixed all
darkness levels, so they're dropped and learnt again.
- Android: the printer sheet shows the speed at the chosen darkness; the time under Print follows the darkness slider.
- Windows: the time under the preview follows the darkness and copies.
**Printer details in the settings** (all versions): which paper to buy (57 mm thermal roll for the SC03h),
whether it takes die-cut labels, print width and resolution. Android: printer sheet; Windows: printer menu › Printer
details…; command line: `ipreent settings`.
- Command line: `ipreent bench` prints one short strip per darkness (lightest, normal, darkest by default; about
  11 cm of paper), times each and shows how much darkness slows the printer. `ipreent settings` lists the speed at
  every darkness. The help for `--speed` said the wrong direction: a higher value prints slower.

## v0.5.0
**Downloads**
- `iPreent-v0.5.0.apk`: Android app (Android 8+). Installs over v0.4.1. Also available through Obtainium (see README).
- `iPreent-v0.5.0-portable.exe`: Windows app. One file, no install, no Python.
- `ipreent-cli-v0.5.0.zip`: command line for Windows, Linux and macOS. Needs Python 3.10+; see `INSTALL.txt`.

iPreent is now open source under the MIT license.

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

**Security**: the Windows HTTP API (local mode) now refuses requests from web pages, so a website can't print on your printer.

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

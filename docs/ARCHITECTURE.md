# Architecture: what lives where

Read this (and [RELEASES.md](RELEASES.md)) instead of re-reading the code at the start of a session. When a change
moves something described here, update this file in the same commit.

## The three apps share one core
```
                ┌──────────── ipreent/ (Python package) ────────────┐
                │ protocol  models  imaging  receipt  convert       │
                │ templates features  busy  config  api  ble  spp   │
                └──────┬───────────────────────────────┬────────────┘
           cli.py (command line)           desktop/ (Windows app, PySide6)
                                                   app · worker · server · spool

   android/app/src/main/java/com/ipreent/  ← Kotlin port of protocol, models, imaging, receipt, templates, features
```
The printer protocol is in [PROTOCOL.md](../PROTOCOL.md): frames `51 78 CMD 00 LEN DATA CRC8 FF`, one 1-bit row
of 384 dots per line frame (raw or run-length), energy/speed/feed commands, and the printer's flow-control
notification. Everything prints by turning content into a list of rows (0/1 per dot) and calling `print_job`.

## Python package `ipreent/`
| Module | Job | Kotlin twin |
|---|---|---|
| `protocol.py` | Frames, CRC8, row encodings, `print_job` byte stream, notification parsing, **print-time estimate** (`speed_for`, `estimate_seconds`, `measured_speed`, `format_eta`; a fixed 10 mm/s, the slowest nominal speed, at every darkness, unless the debug setting overrides it; timed prints are logged, never learnt) | `Protocol.kt` |
| `models.py` + `models.json` | 187 printer profiles (width, dpi, speeds, MTU, RLE, serial-only flag, paper class, label mode) looked up by the longest model number that prefixes the Bluetooth name; `details()` = what the settings screens show (paper to buy, die-cut labels if supported, print width, resolution) and deliberately not ink, speed, transport tuning or vendor flags | `Model.kt` (+ `assets/models.json`) |
| `imaging.py` | Images → gray → 1-bit rows (Floyd–Steinberg, Atkinson, threshold), text with emoji fallback, checklist, banner, QR (segno), Code 128 | `Imaging.kt` |
| `receipt.py` | Receipts (BOLETA): CLP parsing/formatting, totals, layout, receipt number = print time | `Receipt.kt` |
| `templates.py` + `templates/*.svg` + `fonts/` | Templates (docs/TEMPLATES.md): SVG designs with `ip:` text boxes; `parse`, `wrap`/`fit`/`layout` (shrink to fit, stretch at `ip:stretch`), `gallery_order`/`category_order` (`ip:season`: in-season templates and chips first), `render` (art with resvg_py, text with `imaging.draw_text` and the bundled Fredoka/Pacifico fonts), user SVGs from `<config dir>/templates` (Mine) | `Templates.kt` (layout) + `TemplateArt.kt` (AndroidSVG drawing; `assets/templates`, `assets/fonts`) |
| `convert.py` | File type detection, PDF pages (pypdfium2), text files → images | `Sources.kt` (Android loading) |
| `features.py` | Tool weights + decayed usage → home-screen order (`DESKTOP`, `CLI` tables) | `Features.kt` (`ANDROID` table) |
| `busy.py` | One print at a time across programs on a PC: OS lock on `print.lock` + `busy.json` (label, start, estimate, queue behind) | none (Android is one app) |
| `i18n.py` + `locales/*.json` | Language of the CLI and Windows app: system language, or the debug choice (`language.json` in the config dir, env `IPREENT_LANG` wins); `tr("English text {0}", value)` looks the exact English text up in `locales/<lang>.json` and falls back to English for anything missing or broken, `trn` for singular/plural; `locales/templates.<lang>.json` = template names, labels and example texts | `Lang.kt` + `res/values-es` (the template JSON is shared, byte for byte, with `assets/i18n`) |
| `config.py` | Config dir: `%APPDATA%\ipreent` (Windows), `~/Library/Application Support/ipreent` (macOS), `~/.config/ipreent` | SharedPreferences |
| `api.py` | `connect()` (explicit target → remembered printer → scan), `rows_for`, `print_rows` (times each print and calls `log_print`), `estimate`, `known_speed` / `debug_speed` / `set_debug_speed`, sync helpers `print_text/print_file/status` | `Printers.kt` |
| `ble.py` / `spp.py` | Bluetooth LE (bleak) and Bluetooth serial (pyserial / RFCOMM socket) transports | `BlePrinter.kt` (BLE only) |
| `cli.py` | Command line (see below) | |

Shared test cases: `tests/test_protocol.py` ↔ `ProtocolTest.kt` (incl. the SC03h details), `test_receipt.py` ↔ `ReceiptTest.kt`,
`test_features.py` ↔ `FeaturesTest.kt`, `test_templates.py` ↔ `TemplatesTest.kt`. Change both sides together. The template
SVGs and fonts exist twice (`ipreent/templates`, `ipreent/fonts` and `android/app/src/main/assets/`); a Python test
fails if the copies differ.

## Command line (`ipreent/cli.py`)
- Subcommands, listed in `--help` by `features.CLI` weight: `print`, `text`, `receipt`, `status`, `template`
  (list, `--fields`, print or `--preview` a template; texts in field order or `--set KEY=TEXT`), `preview`,
  `queue`, `scan`, `feed`, `settings` (darkness; `paper-speed` = the debug speed for estimates, `reset` = 10 mm/s),
  `forget`, `bench` (one short strip per darkness level, timed, to measure the real speed and show how much
  darkness slows the printer; it doesn't change the estimates). Plain `ipreent` shows an overview (printer, settings, queue,
  three most used commands by weight + usage).
- Connection options (`-a/-p/--rfcomm/--ble/-m`) and tuning (`--width/--energy/--speed/--rle`) work before or
  after the subcommand.
- Printing path: lay out with the remembered model's width → take the print lock (`busy.Lock`; if another program
  holds it, ask "Add this print to the queue? [Y/n]", or queue silently when not on a terminal; `-y`, `--no-wait`) →
  connect → re-layout if the real width differs → print with a countdown → release.
- `status` and `queue` don't connect while someone else prints; they read `busy.json`.

## Windows app (`ipreent/desktop/`)
- `app.py`: `MainWindow` (left: printer card with gear menu, mode list ordered by `features.DESKTOP`, queue with
  countdowns; centre: editor + exact preview; right: print settings, only the rows the mode uses) and `App`
  (tray menu, Ctrl+Alt+P hotkey, single instance via `QLocalServer`, HTTP API, print-dialog bridge, autostart).
  Modes are keys: `photo, document, text, receipt, template, list, qr, banner, barcode` (saved as `mode_key`).
  Printer menu: holding Shift while opening it adds *Debug settings…* (paper speed for estimates, shared with
  the CLI through `timing.json`, and the *Language* override, shared through `language.json`; stays listed
  afterwards, QSettings `debug_unlocked`). Changing the language restarts the app (the windows are built with their
  texts), unless a print is in progress. Qt's own texts (OK, Cancel, file dialogs) come from `qtbase_<lang>.qm`.
  The HTTP API (`server.py`) keeps its messages in English on purpose: programs read them.
  Templates mode: filter chips (scroll sideways; in-season category first) + a horizontal strip of thumbnails (made the first time the mode opens) above the
  chosen template's text boxes; *Add SVG…*/dropped `.svg` files are copied to `<config dir>/templates` (Mine).
  Print → `confirm_busy` (asks if a job is open here or another program holds the lock) → paper-slip animation →
  `worker.print_job(..., lines=)`.
- `worker.py`: one asyncio thread for all Bluetooth work (bleak's WinRT backend can't share Qt's thread). Jobs run
  one at a time; the worker holds the cross-program lock while its queue has jobs. Signals: `queued, started,
  progress, estimate, blocked, finished, status, found`.
- `server.py`: HTTP API (incl. `GET /templates`, `POST /template`, by name only, never a file path), off by default; `127.0.0.1:8787` with no token but refusing browser requests (`Origin`)
  and non-localhost `Host` (DNS rebinding); LAN mode (`0.0.0.0`) needs the bearer token.
- `spool.py`: "iPreent" printer in Windows print dialogs = Microsoft Print to PDF writing
  `C:\ProgramData\iPreent\spool\job.pdf`; the app polls it every second. Install/uninstall via one UAC prompt.

## Android app (`android/app/src/main/java/com/ipreent/`)
- `MainActivity.kt`: Compose UI. Nav bar **Create · Queue · History** (Material 3: 3–5 destinations). Create =
  home grid of `Tool`s (`photo, document, text, receipt, template, list, code, banner`), order fixed per run from
  `Features.ANDROID` + usage (top two get big tiles). Tool screens have a back arrow; the top bar always has the
  printer chip (name + gear → `PrinterSheet`: darkness, status/battery, find, forget; tapping the printer's name
  7 times opens `DebugSettings`, the paper speed for estimates). Print → `BusyDialog` if
  a job is open → `Fly` paper slip to the Queue icon → `Printers.enqueue`. History reprints use the same path.
  Templates tool: `TemplateGallery` (filter chips, in-season templates and chip first, adaptive grid of thumbnails, *Your own SVG* card →
  `filesDir/templates`) → `TemplateEditor` (one text field per box, exact preview, PrintBar); back returns to the gallery.
- **Language**: all UI text is in `res/values/strings.xml` (English, the default) and `res/values-es/strings.xml`
  (Spanish); Android picks one from the system language. `Lang.kt` holds the debug override (SharedPreferences
  `printer`, key `language`: `system`/`en`/`es`), applied in `MainActivity.attachBaseContext`; the Language chips in
  `DebugSettings` save it and recreate the activity. Code without an Activity (queue, print service) gets text through
  `Lang.str(ctx, id, …)`. Pure code that must stay JVM-testable throws `UserError`/`TemplateError` (English `message`
  for tests, string `res` + `args` for the UI; `Lang.text` picks). Template names, box labels and example texts for
  Spanish are in `assets/i18n/templates.es.json` (`Templates.localize`); the SVGs themselves stay shared with Python.
  Anything not translated falls back to English: Android uses `values/` for a string missing from `values-es/` (lint's
  `MissingTranslation` is off so that is not a build error), and a template or box missing from the JSON keeps its English
  text. `LocalizationTest` only checks that what exists matches (no unknown names, same `%` arguments).
  Add a language = a `values-xx/strings.xml`, an optional `templates.xx.json`, and an entry in `Lang.CHOICES`.
  The Windows app and the CLI have their own, equivalent system in `ipreent/i18n.py` (above): same fallback, same
  debug override. Receipts always print in Spanish (BOLETA).
- `Printers.kt`: app-wide state: model table, remembered printer (`printerName` flow), darkness, the queue
  (`QueueEntry`: waiting/connecting/printing/done/failed/cancelled, thumbnail, estimate, progress; cancel waiting
  jobs), estimate speed (nominal 10 mm/s or `debugSpeed`), history (each print saved as its exact 1-bit PNG, last 50).
- `BlePrinter.kt` (GATT transport with flow control), `Protocol.kt`, `Model.kt`, `Imaging.kt`, `Receipt.kt`,
  `Features.kt`, `Sources.kt` (load shared/picked images, PDFs via PdfRenderer, text),
  `IpreentPrintService.kt` (Android print service: "Print" from Chrome/Files shows iPreent).
- Share sheet: `ACTION_SEND` with images, PDFs or text opens the matching tool.

## Where each app keeps state
| App | Where | What |
|---|---|---|
| CLI + Windows (shared) | config dir: `language.json` | `language`: `es` or `en` when forced in the debug settings (absent = follow the system) |
| | `config.json` | remembered printer (name, address/port, transport, model) |
| | `timing.json` | `debug_mm_per_s` (debug speed for estimates; absent = 10 mm/s), number of timed prints, `log` of the last 100 timed prints (energy, lines, seconds, black share, whether the printer said "printing"); older files' learnt `speeds` are ignored and dropped |
| | `print.lock`, `busy.json` | cross-program lock and the job holding it |
| CLI | `receipt.json`, `settings.json`, `usage.json` | receipt header; default darkness; command usage |
| Windows | registry `HKCU\Software\iPreent\iPreent` (QSettings) | print settings, mode, receipt form, template texts (`template_values`, `template_id`), API settings + token, usage, `debug_unlocked` |
| | `HKCU\...\CurrentVersion\Run` | "Start with Windows" |
| CLI + Windows | config dir: `templates/*.svg` | the user's own templates (Mine) |
| Android | SharedPreferences `printer`, `receipt`, `usage`, `templates`; `filesDir/history/*.png`, `filesDir/templates/*.svg` | printer, darkness, `debug_mm_per_s`, `debug_unlocked`, `language`, `last_measured_mm_per_s` (shown in the debug settings only); receipt form; tool usage; template texts (id → JSON); print history; own templates (Mine) |

## Checking changes without hardware
- `pytest -q` (two known Linux failures: no emoji font; `winreg`). Tests never touch the real config dir
  (`tests/conftest.py`).
- Windows window: offscreen on Linux with `QT_QPA_PLATFORM=offscreen`, `winreg` and `ctypes.windll` stubbed.
- Android: `cd android && sh ./gradlew testDebugUnitTest assembleRelease`; screenshots through a temporary
  Robolectric test (CLAUDE.md).
- Hardware so far: SC03h-5363 (cat-face printer, BLE). Manual test logs are in `MANUAL_DEBUGGING.md`.

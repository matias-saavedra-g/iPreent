# Architecture: what lives where

Read this (and [RELEASES.md](RELEASES.md)) instead of re-reading the code at the start of a session. When a change
moves something described here, update this file in the same commit.

## The three apps share one core
```
                ┌──────────── ipreent/ (Python package) ────────────┐
                │ protocol  models  imaging  receipt  convert       │
                │ features  busy  config  api  ble  spp             │
                └──────┬───────────────────────────────┬────────────┘
           cli.py (command line)           desktop/ (Windows app, PySide6)
                                                   app · worker · server · spool

   android/app/src/main/java/com/ipreent/  ← Kotlin port of protocol, models, imaging, receipt, features
```
The printer protocol is in [PROTOCOL.md](../PROTOCOL.md): frames `51 78 CMD 00 LEN DATA CRC8 FF`, one 1-bit row
of 384 dots per line frame (raw or run-length), energy/speed/feed commands, and the printer's flow-control
notification. Everything prints by turning content into a list of rows (0/1 per dot) and calling `print_job`.

## Python package `ipreent/`
| Module | Job | Kotlin twin |
|---|---|---|
| `protocol.py` | Frames, CRC8, row encodings, `print_job` byte stream, notification parsing, **print-time estimate** (`estimate_seconds`, `learn_speed`, `format_eta`; starts at 40 mm/s from the listing's "40 ppm") | `Protocol.kt` |
| `models.py` + `models.json` | 187 printer profiles (width, dpi, speeds, MTU, RLE, serial-only flag) looked up by the longest model number that prefixes the Bluetooth name | `Model.kt` (+ `assets/models.json`) |
| `imaging.py` | Images → gray → 1-bit rows (Floyd–Steinberg, Atkinson, threshold), text with emoji fallback, checklist, banner, QR (segno), Code 128 | `Imaging.kt` |
| `receipt.py` | Receipts (BOLETA): CLP parsing/formatting, totals, layout, receipt number = print time | `Receipt.kt` |
| `convert.py` | File type detection, PDF pages (pypdfium2), text files → images | `Sources.kt` (Android loading) |
| `features.py` | Tool weights + decayed usage → home-screen order (`DESKTOP`, `CLI` tables) | `Features.kt` (`ANDROID` table) |
| `busy.py` | One print at a time across programs on a PC: OS lock on `print.lock` + `busy.json` (label, start, estimate, queue behind) | none (Android is one app) |
| `config.py` | Config dir: `%APPDATA%\ipreent` (Windows), `~/Library/Application Support/ipreent` (macOS), `~/.config/ipreent` | SharedPreferences |
| `api.py` | `connect()` (explicit target → remembered printer → scan), `rows_for`, `print_rows` (times each print and calls `learn_speed`), `estimate`, sync helpers `print_text/print_file/status` | `Printers.kt` |
| `ble.py` / `spp.py` | Bluetooth LE (bleak) and Bluetooth serial (pyserial / RFCOMM socket) transports | `BlePrinter.kt` (BLE only) |
| `cli.py` | Command line (see below) | |

Shared test cases: `tests/test_protocol.py` ↔ `ProtocolTest.kt`, `test_receipt.py` ↔ `ReceiptTest.kt`,
`test_features.py` ↔ `FeaturesTest.kt`. Change both sides together.

## Command line (`ipreent/cli.py`)
- Subcommands, listed in `--help` by `features.CLI` weight: `print`, `text`, `receipt`, `status`, `preview`,
  `queue`, `scan`, `feed`, `settings`, `forget`. Plain `ipreent` shows an overview (printer, settings, queue,
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
  Modes are keys: `photo, document, text, receipt, list, qr, banner, barcode` (saved as `mode_key`).
  Print → `confirm_busy` (asks if a job is open here or another program holds the lock) → paper-slip animation →
  `worker.print_job(..., lines=)`.
- `worker.py`: one asyncio thread for all Bluetooth work (bleak's WinRT backend can't share Qt's thread). Jobs run
  one at a time; the worker holds the cross-program lock while its queue has jobs. Signals: `queued, started,
  progress, estimate, blocked, finished, status, found`.
- `server.py`: HTTP API, off by default; `127.0.0.1:8787` with no token but refusing browser requests (`Origin`)
  and non-localhost `Host` (DNS rebinding); LAN mode (`0.0.0.0`) needs the bearer token.
- `spool.py`: "iPreent" printer in Windows print dialogs = Microsoft Print to PDF writing
  `C:\ProgramData\iPreent\spool\job.pdf`; the app polls it every second. Install/uninstall via one UAC prompt.

## Android app (`android/app/src/main/java/com/ipreent/`)
- `MainActivity.kt`: Compose UI. Nav bar **Create · Queue · History** (Material 3: 3–5 destinations). Create =
  home grid of `Tool`s (`photo, document, text, receipt, list, code, banner`), order fixed per run from
  `Features.ANDROID` + usage (top two get big tiles). Tool screens have a back arrow; the top bar always has the
  printer chip (name + gear → `PrinterSheet`: darkness, status/battery, find, forget). Print → `BusyDialog` if
  a job is open → `Fly` paper slip to the Queue icon → `Printers.enqueue`. History reprints use the same path.
- `Printers.kt`: app-wide state: model table, remembered printer (`printerName` flow), darkness, the queue
  (`QueueEntry`: waiting/connecting/printing/done/failed/cancelled, thumbnail, estimate, progress; cancel waiting
  jobs), learnt speed, history (each print saved as its exact 1-bit PNG, last 50).
- `BlePrinter.kt` (GATT transport with flow control), `Protocol.kt`, `Model.kt`, `Imaging.kt`, `Receipt.kt`,
  `Features.kt`, `Sources.kt` (load shared/picked images, PDFs via PdfRenderer, text),
  `IpreentPrintService.kt` (Android print service: "Print" from Chrome/Files shows iPreent).
- Share sheet: `ACTION_SEND` with images, PDFs or text opens the matching tool.

## Where each app keeps state
| App | Where | What |
|---|---|---|
| CLI + Windows (shared) | config dir: `config.json` | remembered printer (name, address/port, transport, model) |
| | `timing.json` | learnt paper speed (mm/s) and number of timed prints |
| | `print.lock`, `busy.json` | cross-program lock and the job holding it |
| CLI | `receipt.json`, `settings.json`, `usage.json` | receipt header; default darkness; command usage |
| Windows | registry `HKCU\Software\iPreent\iPreent` (QSettings) | print settings, mode, receipt form, API settings + token, usage |
| | `HKCU\...\CurrentVersion\Run` | "Start with Windows" |
| Android | SharedPreferences `printer`, `receipt`, `usage`; `filesDir/history/*.png` | printer, darkness, learnt speed; receipt form; tool usage; print history |

## Checking changes without hardware
- `pytest -q` (two known Linux failures: no emoji font; `winreg`). Tests never touch the real config dir
  (`tests/conftest.py`).
- Windows window: offscreen on Linux with `QT_QPA_PLATFORM=offscreen`, `winreg` and `ctypes.windll` stubbed.
- Android: `cd android && sh ./gradlew testDebugUnitTest assembleRelease`; screenshots through a temporary
  Robolectric test (CLAUDE.md).
- Hardware so far: SC03h-5363 (cat-face printer, BLE). Manual test logs are in `MANUAL_DEBUGGING.md`.

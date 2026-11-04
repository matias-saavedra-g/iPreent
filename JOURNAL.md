# freeprint journal

Running log of findings, decisions, progress and open questions. Newest entries at the bottom of each day.

---

## 2026-10-13

### Goal
Free the user's $5 mini thermal printer from the vendor app (iPrint / Tiny Print, `com.frogtosea.iprint`)
before it gets deprecated or put behind an account. Build an offline driver for Android, Windows, Linux
and macOS. Android and Windows 11 come first.

### Reverse engineering the APK
- Input: split APK (`base.apk` + arm64, en, xxhdpi configs). Decompiled with jadx 1.5.1 on a portable JRE 21
  (no Java on the machine). These tools were set up in a throwaway scratch folder; redo them if needed.
- The app is a large Chinese-OEM codebase (Kotlin + Java, Realm, Firebase, OCR, AI features, PDF/Office libs).
  The printer logic is small and lives in `com.lib.blueUtils`:
  `BluetoothOrder` (commands), `PrintDataUtils` (image → bytes), `BluetoothUtils` (BLE), `BLESPPUtils` (classic serial),
  `PrinterModelUtils` + `com.Utils.PrintModelUtils` (model table).
- **Protocol = the well-known "cat printer" family.** Frame `51 78 CMD 00 LEN_LO LEN_HI DATA CRC8 FF`, CRC8 poly 0x07.
  Lines are sent as A2 (raw, LSB = leftmost pixel) or BF (run-length). Energy AF, speed BD, feed A1, quality A4,
  status A3. Full notes in `PROTOCOL.md`.
- Odd naming in the vendor code: `feedPaper()` actually sends **BD (speed)**, not feed. The real feed is the `paper` constant (A1).
- **The "lock" lives only in the app.** `ActiveDevRequest` / `AddDevRequest` send the printer's MAC to the vendor's
  server, and the reply only flips an app-side `CANPRINT` flag. The printer never receives anything from the server.
  An independent driver skips all of this. This was the main worry, and it's resolved.
- A few models (GT09/GT10, camera printers) use a `d1key` challenge/response (`PrintEncoder`). It's entirely local
  with a hard-coded key, so it can be reproduced offline if ever needed.
- Model table: 196 constructor calls, 187 unique models after removing duplicates. Exported with `tools/extract_models.py`
  → `freeprint/models.json`. Symbolic constants in the decompiled code (e.g. `BannerConfig.LOOP_TIME` = 3000) are
  values jadx swapped in by coincidence; they're mapped back to numbers in the script.
- When a name isn't in the table, the app falls back to: 384 dots, 200 dpi, speed 45, energy 0 (no AF command sent).

### The user's printer
- Unbranded cat-face printer (box says "Tasbel Mini Printer"); the manual has no model number. Bluetooth name **`SC03h-5363`**.
- Table entry `SC03h`: 384 dots, 200 dpi, speed 10, energy 5000 (text 8000), RLE allowed, 180-byte chunks, 4 ms apart,
  `hasId=true`, can print grayscale (gray energy 4100).
- **Key finding: `useSPP=true`.** The app finds it over BLE but prints over **classic Bluetooth serial (RFCOMM)**.
  A BLE-only driver would have connected and printed nothing. Added an SPP transport (COM port, or a raw RFCOMM socket).
- On the serial link the printer controls the pace (an `isFull` flag set from incoming data). I treat AE `10`/`00` as pause/resume.
  ⚠ Unconfirmed on hardware.

### Built (phase 1 CLI, Python)
- `freeprint` package: protocol, models, imaging (Pillow dithering), BLE (bleak), SPP (pyserial / sockets),
  config (remembers the last printer), convert (images, PDF via pypdfium2, text), api, cli.
- Commands: `scan`, `print` (any file, pages, copies, `--no-dither`), `text` (args or stdin), `status [--json]`, `feed`,
  `preview` (PNG + paper length, no printer needed), `forget`. Python API: `freeprint.print_text/print_file/print_image/status`.
- Connect order: explicit target → remembered printer → BLE scan. If the remembered printer fails, it scans again.
  An exception raised inside the caller's own code doesn't trigger a reconnect (there's a test for this).
- Tests: 7 passing (frames byte-identical to the vendor constants, RLE/raw, notification parsing, SPP against a fake link,
  connect/remember logic).
- Bug caught while testing: the "rotate landscape images" rule also rotated rendered text banners. Text now never rotates.
- Repo: https://github.com/matias-saavedra-g/iPreent (APKs not committed: vendor copyright and size).

### Design
- Mockup canvas for phases 2–4: https://claude.ai/artifact/BTdGf9KzfigRY9UrBbFwy9
  (Android home/photo/create/connect, Windows app + system print dialog, tray menu).
  Look: off-white background, black text, teal taken from the printer's color, IBM Plex Sans/Mono.

### Roadmap (from the user)
1. Cross-platform CLI ← **in progress, waiting on a hardware test**
2. Android APK, free and unlocked, plus useful features worth the time (research Reddit first)
3. Portable Windows exe: GUI + standard Windows print dialog
4. Linux/macOS integration (lowest priority)

### Open questions / next
- [ ] **Hardware test on Windows**: pair SC03h → `freeprint status` → `freeprint text "hello"`. Check density
      (energy 5000 may be faint), whether RLE works, and whether the printer sends AE pause/resume over serial.
- [ ] Does SC03h also accept print jobs over BLE (`--ble`)? If so, the Windows setup gets simpler (no pairing / COM port).
- [ ] Grayscale mode for SC03h (BE with 2-byte data, 4-color image data): not built yet.
- [ ] Windows print dialog integration: options are a virtual printer driver (port monitor / PDF-to-printer bridge),
      or reusing Microsoft's "Print to PDF"-style pipeline and watching a folder. Needs research.
- [ ] Reddit research for Android features before building phase 2.
- [ ] Widths for A4 models (GT08/09/10) are approximate (`addMorPix` left padding not handled). Low priority.

### Brand (later on 2026-10-13)
- App brand name: **iPreent** (same as the repo); the Python package/CLI is still `freeprint` for now. Decide whether to rename it.
- Logo in `assets/brand/`: cat-eared printer printing an "i" receipt, teal `#0B6770`. Variants: full icon, small (16–32 px)
  simplified icon, mono `currentColor`, wordmark.
- Rendered and checked: the first wordmark got clipped ("iPreer") because the fallback font was wider. Fixed with
  `textLength`. The full icon gets muddy at 16 px, hence `icon-small.svg`.

### Rename (2026-10-13)
- Python package and CLI renamed `freeprint` → **`ipreent`** (`pip install .` then `ipreent scan`, `import ipreent`).
  The config folder moved too (`%APPDATA%\ipreent`), so a printer saved under the old name has to be found again once.
  The old journal entries still say `freeprint`; that's history, not a mistake.

### First hardware test (2026-10-13, see MANUAL_DEBUGGING.md)
- Windows 11, ThinkPad L14. `ipreent text` → scan found `SC03h-5363`, printed **over RFCOMM** (Windows raised a pairing
  prompt; accepted by hand). The first try said "No printer found" (printer probably still waking up / busy); the retry worked.
- `ipreent --ble text` → **printed over BLE** with no prompt. So SC03h works on both transports.
- Changes from this:
  - SC03h now defaults to BLE (`api.BLE_VERIFIED`), so there's no pairing step. Other `useSPP` models stay on serial until tested.
    `-p COM5` / `--rfcomm` still force serial.
  - Connection and tuning options are accepted after the subcommand too (`ipreent text hi --ble` failed in the test).
- Still unknown: whether the print density is right (no comment yet about faint output), RLE vs raw, and whether AE pause/resume
  ever shows up on serial (43-line jobs are too short to fill the buffer; try a long photo).

### Phase 1 status
CLI works on real hardware → **phase 1 is basically done**. Remaining small checks: a long image (flow control),
density/`--energy` tuning, `status`. Next: phase 2 (Android), starting with the Reddit feature research.

### Open questions (updated)
- [x] Hardware test on Windows: works (RFCOMM and BLE).
- [x] SC03h accepts jobs over BLE: yes → now the default.
- [ ] Density OK at energy 5000/8000? Long photo print (flow control)? `ipreent status` output?
- [ ] Grayscale mode for SC03h. Not built.
- [ ] Windows print dialog integration (phase 3): needs research.
- [ ] Reddit research for Android features (phase 2): next.
- [ ] A4 model widths (low priority).

### Phase 2 research (2026-10-13)
- Reddit is blocked for the research tool (403 for the crawler), so this comes from reviews, app listings and
  open-source projects. The user could paste a few Reddit threads to fill the gap.
- Other apps and what they offer: WalkPrint (notes/lists on preset designs, **banner mode** = long print with huge
  rotated text; the review calls it buggy), NaitLee's Cat Printer (open source, many platforms), MeowPrinter (open source,
  dithering modes, **automatic QR/barcode detection** for crisp output), Fun Printer (templates, QR, **print queue**),
  RawBT (an Android **print service** used as a generic driver).
- What people use them for: to-do lists and reminders, labels, study notes, stickers, photos.
- Proposed Android feature list (v1 → later):
  1. **Share sheet target**: share an image, PDF or text from any app → it prints. The biggest win over the vendor app.
  2. **Android Print Service** so "Print" from Chrome, Files, Gallery and Docs shows iPreent (like RawBT).
  3. Photo with live preview: dither choice (Floyd–Steinberg, Atkinson, threshold), brightness/contrast, energy.
  4. Quick text / checklist / banner (huge rotated text) modes; QR and barcode generator printed crisp (no dither).
  5. Print queue + history (reprint), remembered printer, battery/paper status.
  6. Later: home-screen widget or Quick Settings tile ("print clipboard"), templates, grayscale for SC03h.
- Tech: Kotlin + Jetpack Compose. Port `protocol.py`/`imaging.py` (small, pure) and reuse the test vectors. BLE first
  (SC03h works over BLE), SPP via `BluetoothSocket` for the other `useSPP` models.

### Density + phase 1 closed (2026-10-20)
- Hardware: photos print well at every energy tried (5000–17500). Only print time and visibility of details change.
- CLI presets: `--energy lightest|lighter|normal|darker|darkest` = 5000/6000/8000/12000/17000, **default 8000** (all models).
- `ipreent status` works (state: ready); the SC03h does not answer the battery request.
- The earlier "unrecognized arguments: --energy" came from a stale non-editable install; now installed with `pip install -e .`.
- **Phase 1 done.**

### Phase 2: Android app started (2026-10-20)
- `android/`: Kotlin + Compose, minSdk 26, BLE only (SC03h is verified on BLE). Build:
  `cd android && ./gradlew assembleRelease` (JDK 17 + SDK in `%LOCALAPPDATA%\Android\Sdk`, no Android Studio).
- Ported `protocol`/`models`/`imaging`; `ProtocolTest` reuses the Python test vectors (pass).
- v1 features built: share-sheet target (image/PDF/text), Android Print Service, photo tab (Floyd–Steinberg / Atkinson /
  threshold, brightness, contrast, exact 1-bit preview), text, checklist, banner, QR/barcode, darkness presets,
  print queue, history with reprint (last 50, saved as the printed PNG), remembered printer, status.
- Not yet: on-phone hardware test, SPP transport for non-BLE models, widget / Quick Settings tile, templates, grayscale.

### Android hardware test (2026-10-20, later)
- All features work on the phone (photos, PDFs, text, list, banner, QR, history). The user is very happy.
- Print service failed: "File descriptor not seekable" (the spooler hands over a pipe; PdfRenderer needs a file).
  Fixed by copying the job to a temp file first. **Not retested yet.**
- App now uses Material You (wallpaper colours on Android 12+) and follows the system light/dark theme.
- Brand colour changed from teal to **baby blue `#89CFF0`** (deeper blue `#4A90B8` for slot/wordmark), in the app and `assets/brand/`.

### Phase 3: Windows app started (2026-10-20)
- `ipreent/desktop/`: PySide6 app reusing the Python package. Layout follows the mockup (printer card, Create modes,
  queue | preview | print settings). Modes: image/PDF (drop, paste, open), text, checklist, banner, QR (segno).
  Dithering Atkinson / Floyd–Steinberg / threshold, darkness presets, brightness, contrast, pages, copies.
- Bluetooth runs on its own asyncio thread (bleak's WinRT backend and Qt's main thread don't mix); jobs queue one at a time.
- Tray: print clipboard (global hotkey Ctrl+Alt+P via RegisterHotKey), print file, quick note, feed, start with Windows
  (HKCU Run key). Single instance: a second launch (e.g. "Open with") hands its files to the running one.
- **Print dialog**: no custom driver. A printer "iPreent" on the built-in *Microsoft Print To PDF* driver with a local
  port that is a file (`C:\ProgramData\iPreent\spool\job.pdf`); the app polls it, renames it once the spooler lets go,
  renders pages at 5x, trims white margins, skips blank pages, prints sharp (threshold) by default. Install/uninstall via
  one UAC prompt from the tray menu. **Not tested yet** (needs admin + a real job).
- Portable exe: `python tools/build_windows.py` → `dist/iPreent.exe` (~65 MB, PyInstaller one-file). Starts and opens
  its window; **not hardware-tested yet**. `--debug` builds a console version that shows tracebacks.
- Open: A4 pages printed through the dialog may come out tiny when they're mostly text across the full width
  (trimming only helps when content is narrow). A custom narrow paper size would need a real driver.

### Windows app tested + Fluent + API (2026-10-20, later)
- User tested the exe: everything works, including the print-dialog printer. Asked for Fluent Design and an API.
- Fluent: Qt's `windows11` style, Segoe UI Variable, Mica backdrop (DWM attribute 38 + frame extended into the client
  area, Windows 11 22H2+; without the frame extension the window rendered black), dark title bar, system accent for
  selection and the Print button (text black/white from the accent's brightness). Follows light/dark live.
- HTTP API (`ipreent/desktop/server.py`, stdlib `ThreadingHTTPServer`): default 127.0.0.1:8787, optional LAN mode
  (0.0.0.0) that requires a bearer token. Endpoints in the README. `/print` detects PDF/image/text from the bytes
  (in memory, no temp files: Windows file locks broke the first version). Tested: unit tests + a real print via
  `curl /text?wait=1` → done.

## 2026-11-04

### Receipt mode (all versions)
- User asked for a receipt mode in the CLI, the Windows app and the Android app: business name, address, website,
  products with quantity and price, total in CLP shown with `$`, and a barcode. The barcode doesn't have to look
  anything up: no server and no storage synced between devices.
- Shared logic in `ipreent/receipt.py`, ported to `android/.../Receipt.kt` (the same layout and the same test cases in
  `tests/test_receipt.py` / `ReceiptTest.kt`).
- **Receipt number = print time `YYMMDDhhmmss`** (12 digits, so Code 128 set C fits at 3 dots per module on 384-dot
  paper). Each device can make it alone with no counter, which is what the user wanted. `--number` / API `"number"` replace it.
- Money: whole pesos, `12.990` / `12,990` / `$12.990` all read as 12990. A separator followed by only 1–2 digits at the end
  counts as decimals and gets rounded. Negative price = discount line. Decimal quantities (`0,35` kg) are allowed;
  line amounts are rounded half up. Format `$12.990`, `-$1.000`.
- Look: bold sans business name, monospace body (the classic receipt look), dashed separators, date/time + `N°`,
  name left / amount right with `2 x $2.990` underneath, "Items" count, big bold TOTAL between a solid rule and a double
  rule, a footer message (default "Thank you for your purchase!"), and the barcode with its digits underneath.
  No large black areas (no inverted total bar) so weak batteries aren't strained.
- CLI: `ipreent receipt -b … --addr … --url … -i NAME PRICE [QTY] …`, `--items-file CSV`, `--json FILE|-`, `--preview PNG`.
  `--address` was already taken (BLE address), hence `--business-address` / `--addr`. Header details are remembered in
  `receipt.json` next to `config.json` (separate file because connecting rewrites `config.json`).
- Windows: "Receipt" mode with a business form plus a products table (Product / Qty / Price), all kept in QSettings.
  HTTP API `POST /receipt`. Android: "Receipt" tab (business details fold away once filled), kept in SharedPreferences.
  Both rebuild the receipt when Print is pressed, so the time and number are when it prints, not when it was typed.
- Checked: Python tests; desktop window driven offscreen on Linux (winreg/DWM stubbed); Android `assembleDebug` +
  unit tests; Android bitmap rendered once through a temporary Robolectric test (removed). **Not tested on real
  hardware or Windows/phone yet.**
- Pre-existing on Linux only: `test_emoji_text_uses_emoji_font` (no emoji font) and `test_print_detects_image`
  (`server.py` imports `desktop/app.py`, which imports `winreg`) fail here, as they did before this change.

### Open
- [ ] Print a receipt on the SC03h (check that the monospace body and 3-dot barcode come out crisp and the barcode scans).
- [x] Spanish labels: done (see below).

### Receipt labels in Spanish (2026-11-04, later)
- User's call: use `BOLETA` even though it's a tax-document name in Chile, because these prints can't be mistaken for a
  real one (68 mm printer, plain white paper with no signature or watermark, no SII stamp).
- `RECEIPT` → `BOLETA`, `Items` → `Artículos`, `TOTAL` unchanged, default footer → `¡Gracias por su compra!`.
  A footer someone already saved (CLI `receipt.json`, Windows QSettings, Android prefs) keeps its old text until edited.

### First GitHub Release: v0.4.0 (2026-11-04, later)
- `.github/workflows/release.yml`: APK (Ubuntu, tests run first), portable exe (`windows-latest` + PyInstaller, since it
  can't be built from Linux), and a CLI zip (source + `INSTALL.txt`, for `pip install .`). Notes come from the
  matching `CHANGELOG.md` section. Triggered by a `v*` tag push, or by hand with a `version` input, in which case
  the release step creates the tag itself.
- The cloud session's git proxy refuses tag pushes (HTTP 403), so v0.4.0 was made with the manual run.
  https://github.com/matias-saavedra-g/iPreent/releases/tag/v0.4.0
- Version 0.4.0 everywhere (Android versionCode 2). The APK is signed with the CI runner's throwaway debug key unless
  the `ANDROID_KEYSTORE_*` secrets are set. Until then, every release needs an uninstall before installing.
- [ ] Add a release keystore as repository secrets so later APKs update in place.

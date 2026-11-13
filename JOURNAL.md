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

### Signed APKs: v0.4.1 (2026-11-04, later)
- The build-only run #2 (23:13 UTC) warned "No ANDROID_KEYSTORE_BASE64 secret": the secrets weren't visible to the
  workflow at that moment. Build-only run #3 (23:22 UTC) confirmed them: APK signed by `CN=iPreent, O=MT, C=CL`,
  SHA-256 matching the release certificate.
- Workflow hardened: a publishing run now **fails** without the keystore secret (a build-only run still just warns),
  and a new step runs `apksigner verify --print-certs` and checks the SHA-256 against the release certificate
  (`RELEASE_CERT_SHA256` in `release.yml`).
- v0.4.1 (versionCode 3) is cut instead of re-uploading v0.4.0, so the debug-signed v0.4.0 APK isn't silently swapped
  for a different file under the same name. Phones with v0.4.0 must uninstall once; later versions update in place.
- Gradle notice "8.11.1 is out of date": left as is for now. The current line is Gradle 9, which needs a newer AGP
  (we're on 8.7.3) and likely a Kotlin bump too; that's a build-toolchain upgrade to do on its own and test, not
  inside a signing release. It's an info notice, the build is unaffected.
- [ ] Upgrade Gradle 9 + AGP + Kotlin in a separate change (check the AGP/Gradle compatibility table first).

## 2026-11-05

### Busy printer, home screen, printer settings (all versions)
User asked for three things in the CLI, the Windows app and the Android app:
1. A confirmation when Print is pressed while the printer is already printing (you can't see it working unless
   you look at the paper slot), an animation from Print to the queue, and a time estimate from the printer speed.
2. A better layout than seven squeezed bottom tabs: research the best practice (scrolling tabs vs home screen),
   give each feature a weight and order by likely use.
3. Make the printer button read as settings (gear), again following best practice.

**Research and decisions**
- Material 3 / Android docs: a navigation bar is for **3–5 destinations of equal importance**
  (developer.android.com/develop/ui/compose/components/navigation-bar); the old Material bottom-nav page says the
  same and that scrollable bottom navigation isn't a pattern. Scrollable *tabs* are for content inside one screen,
  not for app-level destinations. So: nav bar with **Create · Queue · History**, and Create is a home screen with
  every tool on it. Queue is always one tap away (with a badge), which is what the user wanted.
- Tool order: prior weights (photo .24, document .20, text .18, receipt .14, checklist .10, codes .08,
  banner .06; Windows splits codes into QR .05 / barcode .03) plus decayed usage counts (×0.9 per use; prior ×10, so
  counts can outweigh the guess after a habit forms). Adaptive-menu research (split menus: Sears & Shneiderman 1994;
  Findlater & McGrenere 2004; Gajos et al. 2008) says moving items hurts unless predictions are good, and holding
  updates back keeps things predictable. So the order is computed **once per app start**, the top two get big tiles,
  and the rest stay in a stable grid. Photo and Document are now separate tools (user's suggestion): documents print
  sharp (threshold) by default and aren't auto-rotated.
- Printer settings: Android chip = printer icon + name + **gear** (M3 assist chip with trailing icon), opening a
  modal bottom sheet (touch-friendly, room for a darkness slider and actions) instead of the old dropdown with radio
  buttons. When no printer is set it says "Set up printer" on a tinted chip. Windows: the printer card has a gear
  and the whole card is clickable (menu: darkness, status/battery, change, feed, forget). CLI: `ipreent settings`.
  WinUI guidance favours a left NavigationView for top-level pages, which the Windows app already had; it now has
  icons (Segoe Fluent/MDL2 glyphs) and the weighted order.
- **"40 ppm"**: a roll has no page size, so it's read as 40 mm/s. Shops list 57 mm printers at 10–90 mm/s, so
  this is only a starting point: every finished print (≥ 20 mm) is timed and blended in (30% per print,
  clamped 5–100 mm/s). Estimate = 3 s connect + per copy (paper + 96-line feed) / speed + 1 s. CLI and Windows share
  the learnt speed (`timing.json`); Android keeps its own. Shared test cases in `test_protocol.py` / `ProtocolTest.kt`.

**What was built**
- `ipreent/busy.py`: an OS lock on `print.lock` (fcntl / msvcrt, released by the OS if the program dies) plus
  `busy.json` with label, start, estimate and what's queued behind. The CLI asks "Add this print to the queue?
  [Y/n]" and waits with a countdown; `-y`, `--no-wait`; non-interactive runs just queue. The Windows worker holds
  the lock while its queue has jobs, so the CLI waits for the whole Windows queue. `ipreent status` and
  `ipreent queue [--watch|--json]` report the other program's job instead of trying to connect.
- CLI: plain `ipreent` shows printer, settings, queue and the three most used commands (`features.CLI` + usage);
  `--help` lists commands by weight. `ipreent settings darkness …` becomes the default `--energy`.
- Windows: busy dialog (also when the CLI holds the lock), paper slip animated along an arc from Print to the queue
  with the new row flashing, queue rows with "starts in" / "left" countdowns and a summary, paper length + time
  under the preview, settings rows shown only for the modes they apply to. Saved mode moved from a row number to
  a key (`mode_key`); old row numbers are mapped. Tray quick prints and HTTP API jobs queue without asking
  (no window to ask in; scripts shouldn't block); `/jobs` replies include `"seconds"`.
- Android: `Printers.queue` (waiting/connecting/printing/done/failed/cancelled, thumbnail, estimate, progress,
  cancel waiting jobs), a "now printing" strip above the tools, the Queue screen, a busy dialog (it says "the printer
  is free now" if the queue empties while it's open), a paper slip flying from Print to the Queue icon with a bounce,
  and the estimate next to the copies counter. History reprints go through the same check and animation.

**Checked**: pytest (40 pass; only the two known Linux failures); CLI prompt in a real pty; the Windows window
driven offscreen (routing, busy dialog incl. a foreign lock holder, animation mid-flight, queue texts, gear menu,
next-launch order); Android unit tests (15) + `assembleRelease`; Compose screens rendered with a temporary
Robolectric test (home, busy home, tool screen, printer sheet, busy dialog, queue), removed afterwards.
**Not tested on hardware, on Windows itself or on a phone yet**, so the speed estimate is unverified.

### Open
- [x] Time a few real prints on the SC03h and check the learnt speed settles (and whether darkness changes it a lot;
      if so, learn one speed per darkness level). → per-level learning built 2026-11-05 (see below); numbers pending.
- [ ] Check the Segoe glyph code points render as intended on Windows 10 and 11 (banner = Flag E7C1, barcode = Tag E8EC).

### Obtainium, pre-public audit, docs for future sessions (2026-11-05, later)
- User asked for an Obtainium link in the README, an audit to decide whether the repo can go public, and docs that
  explain each release so later sessions don't have to analyse the code; then merge everything into `main`.
- Obtainium: same pattern as the user's `claude-usage-widget` README, the redirect badge
  `https://apps.obtainium.imranr.dev/redirect?r=obtainium://add/https://github.com/matias-saavedra-g/iPreent`
  (format from wiki.obtainium.imranr.dev/deep_links). Works without a token only once the repo is **public**.
- Audit (details in SECURITY.md): no secrets in any commit or file ever committed (keys, keystores, passwords,
  tokens, `.env`, `local.properties`); the removed Kotlin error log only had proxy settings; the release workflow
  can't be triggered by forks and doesn't splice `${{ }}` into scripts. GitHub's secret-scanning tool isn't
  available while the repo is private (no Advanced Security), so the scan was done with git grep over all commits.
- **Fixed**: the local HTTP API (no token on 127.0.0.1) accepted requests from any web page, so a site could POST
  `/text` and print, or read `/status` through DNS rebinding. Local mode now refuses an `Origin` header,
  `Sec-Fetch-Site: cross-site/same-site`, and any `Host` other than localhost. Test added.
- Left for the owner to decide: no LICENSE file (public without one = all rights reserved); `models.json` comes
  from the decompiled vendor app (parameters only, for interoperability); Windows username and printer MAC in
  `MANUAL_DEBUGGING.md` logs.
- New docs: `docs/ARCHITECTURE.md` (module map, twins, state locations), `docs/RELEASES.md` (the three downloads),
  `SECURITY.md`. CLAUDE.md now points to them; its release section was shortened to the pitfalls.

### v0.5.0 (2026-11-05, later)
- MIT license added (LICENSE, pyproject, README; the CLI zip now includes it). Version 0.5.0, versionCode 4. Release started with a manual workflow run.

### Print speed: slower start, one speed per darkness (2026-11-05, later)
- User: real prints are much slower than the 40 mm/s estimate, and suspects darkness (energy) slows printing in
  proportion. Little paper left, so asked for online data first, else a cheap benchmark.
- Research: no published measurements of cat-printer speed vs energy. Spec sheets for 57 mm pocket printers give
  10-15 mm/s (Phomemo M02/M02 Pro, generic "mini cat" listings); 30-70 mm/s figures are outliers. NaitLee's
  Cat-Printer (`printer_lib/commander.py`): BD speed is "the lower, the quicker" (our `--speed` help said the
  opposite; fixed), energy AF max 0xFFFF. Physically, more energy = longer burn per line, so a heat-limited head
  slows with energy; the 2026-10-20 hardware note already said darkness changed print time.
- Built (Python + Kotlin, shared cases): `speed_for(energy, learnt)` = learnt figure, else interpolate seconds/mm
  between learnt neighbours, else scale from the nearest learnt level (or 15 mm/s at 5000) as time ∝ energy.
  `learn_speeds`: first timed print at a level replaces the guess, then 30 % blending. Old single `mm_per_s`
  dropped (mixed levels). Estimates everywhere use the job's energy. `timing.json` keeps a `log` of the last 100
  timed prints (energy, lines, seconds, black share, `busy_seen`) so the model can be checked from everyday prints.
  `ipreent bench`: one strip per level (label + 30 mm of 50 % pattern), no feed between strips, 0.1 s polling.
- Doubt to check on hardware: `wait_done` stops at the first state reply without the "printing" bit. If the SC03h
  never sets it, timings end when the data is sent, not when the paper stops (too fast). `busy_seen` in the log
  and the bench output show this; compare one print against a stopwatch.

### Open
- [ ] User to run `ipreent bench` (or print normally at different darkness levels) and send `timing.json`; then set
      the starting guess and the energy scaling from real numbers.

### Nominal speed range, printer details (2026-11-05, later)
- User: no paper left (last roll finished), so no benchmark for now. Use the nominal figures: 15 mm/s at
  lightest, 10 mm/s at darkest. `nominal_speed(e)`: seconds/mm linear in energy between 5000 and 17000, continued
  past the darkest, never faster than the lightest (Normal 13.3, Darker 11.6). Untimed levels next to a timed
  one follow this curve's ratio instead of proportional scaling.
- Printer details in all three settings screens from what models.json already has, no web lookup. Kept: paper
  to buy (from the vendor `size` code: 1 = ~15 mm label tape, 2 = 57 mm roll, 3 = 80 mm, 4 = 4-inch, 8 = A4;
  named from each code's print widths), paper types (`canPrintLabel` → die-cut labels too), print width, dpi,
  "no ink, fades with heat", and the speed range. Left out: MTU, chunk interval, RLE, new frame format, speed byte,
  raw energies, `hasId`, `backPaperNum`, `detectionValue`, `oneLength`, `headName`: transport tuning or vendor
  internals that don't help choose paper or settings. Grayscale (vendor code says SC03h can) not shown: not built.
- Open: roll diameter / core size isn't in the vendor table; would need the printer's manual.

### v0.5.1 (2026-11-05, later)
- User trimmed the printer details: no "Ink" line, no generic paper types (only "Labels" when the model has the
  die-cut label mode), no paper speed (the CLI `settings` paper-speed line and Android's speed line stay).
- The v0.5.0 workflow didn't start, so this is released as v0.5.1 (versionCode +1), started with a manual
  `release.yml` run on main.

## 2026-11-06

### Templates: cute SVG designs to fill in (all three apps)
- User: a collection of cute, editable designs (frames, hearts with text inside, lists…) in the CLI, the Windows
  app and Android, using the existing printing functions plus a new "collection" function. Asked for research on
  what to build and how; won't be around to answer questions, so the decisions below are mine.
- UX research (sources in docs/TEMPLATES.md): the template-gallery pattern (ui-patterns.com) = preview every
  template, one tap to an editable copy pre-filled with realistic sample text, a small curated set with
  categories (a big undifferentiated gallery recreates the blank page as a choice problem), keep a blank option.
  Filter chips: single-select, short nouns, horizontal scroll (CMS design system; Material 3 same). What people
  print on pocket printers (Phomemo blogs): to-do lists, journal stickers, notes, labels, gift tags, thank-you
  notes. Label-printer apps (Niimbot, Phomemo, Stikkr) do templates + inline text; their reviews complain the print
  doesn't match the screen → our preview is the exact 1-bit print. Threshold (not dithering) for text and line art
  (Label LIVE, Neodynamic, Zebra).
- Design: a template = an ordinary SVG + `ip:` attributes (namespace `urn:ipreent:template`): root `ip:name`,
  `ip:category`, `ip:stretch`; invisible rects with `ip:field` etc. as text boxes. Art by resvg (PC) / AndroidSVG;
  text drawn by us so it shrinks to fit (largest whole size from `ip:size` to `ip:min`), wraps, falls back to emoji
  fonts and can **stretch** the design (repeat the pixel row at `ip:stretch`, move boxes below) when it doesn't fit
  at the minimum. Self-contained SVGs also let users bring their own files (Mine) without a separate manifest.
- Renderers: `resvg_py` 0.5.0 (MIT, abi3 wheels incl. Windows; needs Python ≥3.10, so `requires-python` is now
  3.10 as INSTALL.txt already said). CairoSVG rejected (Cairo DLL on Windows), Qt SVG rejected (SVG Tiny only, and
  the CLI doesn't depend on PySide6). Android: AndroidSVG 1.4 (Apache 2.0; last release is old but it's what Coil
  uses). **Pitfall found**: AndroidSVG draws at the root `width`/`height` and ignores `RenderOptions.viewPort`'s
  size; `setDocumentWidth/Height("100%")` (plus a viewBox when missing) fixes it. It only showed at widths other
  than 384, so thumbnails (and 80 mm printers) would have been wrong.
- Fonts: Fredoka SemiBold ("round") and Pacifico ("script"), SIL OFL 1.1 (license files next to them), taken
  from the `@expo-google-fonts` npm packages; both have Spanish accents and ¡¿.
- Collection: 20 original designs (MIT) in 6 categories (love, frames, lists, notes, party, labels), drawn at 384
  units wide with ≥3-unit strokes and few large black areas (heat, speed, curl). Lists and notes stretch; the
  minimum font sizes of stretching boxes are close to their maximum so they grow rather than go tiny.
  Generated once with a scratch script (not committed); the SVG files are the source now.
- Built: `ipreent/templates.py` ↔ `Templates.kt` (layout; shared cases in `test_templates.py` ↔ `TemplatesTest.kt`,
  hand-checked numbers) + `TemplateArt.kt` (drawing). CLI `ipreent template` (list / `--fields` / print /
  `--preview`, texts in order or `--set KEY=TEXT`, `\n`, `-` = stdin, any `.svg` path). Windows: Templates mode (chips,
  thumbnail strip, text boxes, Add SVG / Folder / drop, texts remembered per template). HTTP API `GET /templates`,
  `POST /template` (names only, no file paths). Android: Templates tool (chips, adaptive grid, editor, *Your own
  SVG* → `filesDir/templates`, remove from Mine). Feature weights: template 0.10 on Android/Windows, 0.07 CLI.
- Checked: pytest (only the two known Linux failures); Windows window driven offscreen (gallery, typing, filter,
  print, settings saved); Android `testDebugUnitTest assembleRelease`; Robolectric screenshots of every template
  (identical layout to the Python renders), the gallery and the editor (temporary test, removed).
  **Not tried on a real phone, on Windows itself or on paper yet.**

### Open
- [ ] Print a few templates on the SC03h: check stroke weights, the script font at small sizes and that the big
      black areas (ribbon, name tag) don't streak or slow the print too much.
- [ ] Windows: check the template glyph (Heart, U+EB52) in the nav list on Windows 10 and 11.
- [ ] Maybe later: more templates (seasonal: Christmas, Fiestas Patrias, Halloween), a "label sheet" that repeats a
      small design, and photo slots (a frame around a picture).

### v0.6.0 (2026-11-06, later)
- User approved the templates. Example names in templates and docs are now Matías and Yuliana (birthday, name tag,
  gift tag). Version 0.6.0, versionCode 6; merged into main. Release workflow not started yet.

## 2026-11-07

### Print times: fixed 10 mm/s, debug settings (all three apps)
- User: the learnt print times weren't accurate. Fix the estimate at 10 mm/s and assume the slowest setting; allow
  changing it only from hidden debug settings. Won't be around; updates go to Telegram.
- Decision: `speed_for(override)` = the debug value or `NOMINAL_MM_PER_S = 10.0` (the old darkest nominal), the
  same at every darkness. Removed the per-energy learning (`learn_speed(s)`, `nominal_speed`, energy curve) from
  `protocol.py` ↔ `Protocol.kt`. Timed prints are still logged (`timing.json` `log`; Android keeps only
  `last_measured_mm_per_s`) and shown in the debug settings as "not used". Old learnt `speeds` are ignored and
  dropped on the next write, so upgrading users get 10 mm/s at once.
- There were no debug settings yet. Added: Android = tap the printer's name in the printer sheet 7 times (Android's
  "build number" convention, with a countdown toast from the 3rd tap; *Hide* puts them away); Windows = hold Shift
  while opening the printer menu (stays listed afterwards); CLI = the existing `ipreent settings paper-speed`
  (now one value, `reset` = 10). CLI and Windows share it via `timing.json` `debug_mm_per_s`.
- Checked: pytest; Windows debug dialog driven offscreen (set 14 → estimates 14; Nominal → 10, key removed);
  Android unit tests; Robolectric render of the debug section (temporary, removed).

### Christmas and holiday templates
- User: a collection of holiday SVGs, especially Christmas; no Thanksgiving (not celebrated in Chile).
- 17 designs, drawn with a scratch generator (not committed; the SVGs are the source): `christmas` category
  (70-77: tree, gift tag, ornament, letter to the Viejito Pascuero, snowflake frame, countdown, stocking, wreath)
  and `holidays` (80-88: New Year, Fiestas Patrias, Halloween, Valentine's, Easter, Mother's, Father's, Children's,
  Teachers' Day). Chilean dates: Mother's Day 2nd Sunday of May, Father's Day 3rd Sunday of June, Children's Day
  2nd Sunday of August, Teachers' Day 16 October. Spanish example text only where the holiday is Chilean.
- New `ip:season="MM-DD..MM-DD"` (inclusive, may wrap past New Year): galleries put in-season templates and their
  chip first (`gallery_order` / `category_order` ↔ `galleryOrder` / `categoryOrder`, shared test cases). The CLI
  keeps file order so `ipreent template N` stays stable.
- Two clip-paths (egg, tie) and one on the ornament: render the same in resvg and AndroidSVG (checked with
  Robolectric).
- Windows: two more chips pushed the window's minimum width from about 1260 to 1367 px; the chip row is now a
  horizontal scroll area (minimum 938 px).

### v0.7.0
- Version 0.7.0, versionCode 7; merged into main and the release workflow started from main.

### Open
- [ ] Print the new templates on the SC03h (thin snowflake arms at 3 units, the wreath's many leaves, the hatched flag).
- [ ] Time a few real prints against a stopwatch; if 10 mm/s is far off, change the nominal value (one constant per
      app) instead of using the debug setting.

## 2026-11-13

### Android app in Spanish, with a language override in the debug settings
- User: translate the whole app to Spanish, follow the system language, and let the debug settings override it.
- Everything was hard-coded English in Kotlin, so all of it moved to `strings.xml` (+ `values-es`); Android picks the
  language itself. Override: `Lang.kt` wraps the activity's context with the chosen locale (`attachBaseContext`) and
  sets `Locale.getDefault` so numbers and dates follow; changing it recreates the activity (the printer sheet is
  `rememberSaveable` so it reopens). System language is read from `Resources.getSystem()`, not `Locale.getDefault`,
  because the latter is ours once overridden. A system language other than es falls back to English.
- Pure code (`Receipt`, `Templates`, `Protocol.describeState`) keeps English messages for the tests and the Python twin;
  errors carry a string resource too (`UserError`, `TemplateError`) and `Lang.text` translates them in the UI.
- Templates: 37 names + box labels + example texts in `assets/i18n/templates.es.json` instead of editing the SVGs,
  which are shared byte for byte with the Python package. Typed template text is now stored only when it differs
  from the example text, so untouched boxes follow the language.
- History file names kept only `A-Za-z0-9`, which would have turned "código" into "cdigo"; they now keep any letter.
- Spanish choices: «tú», Chilean wording (Agregar, Boleta, Fiestas Patrias kept), tool *Banner* → *Letrero*, *Darkness*
  → *Intensidad*, category *Mine* → *Mis diseños*. Say if any should change.
- Checked: unit tests (new `LocalizationTest`), `assembleRelease`, and a temporary Robolectric test (removed) that
  system es/en/fr and both overrides pick the right strings, plural forms and translated errors. Not looked at on a
  device or with screenshots: long Spanish labels (e.g. "Ancho de impresión", the home tiles) may wrap or clip.

### Open
- [ ] Look at the Spanish screens on a phone (or Robolectric PNGs) for clipped text.

### Untranslated text falls back to English
- User asked for it. Android already does this for strings (`values/` is the default), but release lint made a missing
  translation a build error and `LocalizationTest` demanded full coverage; both relaxed (`lint { disable += "MissingTranslation" }`,
  test checks only that existing translations are known and keep the same `%` arguments). Template JSON entries may be
  partial. Checked by deleting two Spanish strings: tests and `assembleRelease` still pass.

### Windows app and command line in Spanish (v0.8.1)
- User: translate everything, same behaviour (system language, debug override), English fallback always.
- Python has no resource system, so `ipreent/i18n.py`: the English text is the key (`tr("Found {0}", x)`), the catalog is
  `locales/es.json`, and anything missing, empty or with wrong placeholders falls back to English (tested). f-strings
  became numbered placeholders so Spanish can reorder; singular/plural pairs use `trn`. A scratch script (not
  committed) did the first wrapping of ~330 strings by AST; a few (plurals, nested conditionals, state words) by hand.
- System language: `GetUserDefaultLocaleName` on Windows, `LC_ALL`/`LC_MESSAGES`/`LANGUAGE`/`LANG` elsewhere. The
  debug choice is `language.json` in the config dir, shared by the CLI and the Windows app like `timing.json`;
  `IPREENT_LANG` beats it (tests set it to `en` before anything is imported).
- Windows: the widgets are built with their texts, so a language change **restarts the app** (single-instance
  socket released first, API stopped, no restart while a print is open: then it applies on the next start). Qt's own
  buttons come from `qtbase_es.qm` (PySide ships it; OK → Aceptar checked offscreen).
- argparse: `argparse._ = tr` so "usage:", "options" and errors are Spanish too; the main docstring is one catalog key.
- Template names, labels and example texts: `locales/templates.es.json` is the same file as Android's
  `assets/i18n/templates.es.json` (a test compares them). `CATEGORIES` keeps English names; `category_name()` translates.
- Kept English on purpose: HTTP API messages (programs read them), command names, flags and settings keys
  (`darkness`, `paper-speed`, `language`), receipt text (already Spanish).
- Checked: pytest (new `tests/test_i18n.py`), the CLI in Spanish (`--help`, overview, settings, template list and
  `--fields`, errors), the Windows window and debug dialog rendered offscreen in Spanish (all nine modes).
  Not checked on Windows itself: the restart after changing the language, the Windows system-language detection.

### Open
- [ ] On Windows: change the language in the debug dialog and see the app restart in the other language.
- [ ] Look at the Spanish Android screens on a phone for clipped text.

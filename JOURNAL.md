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

# iPreent

![iPreent](assets/brand/logo.svg)

Offline, account-free driver for the cheap BLE thermal "mini printers" (cat-face printer,
GB01/GB02/GB03, X6, MX…) that normally need the **iPrint** / **Tiny Print** app.
No login, no internet, no vendor server. Protocol notes: [PROTOCOL.md](PROTOCOL.md).

## Windows 11 (also Linux / macOS)
1. Install Python 3.10+ from python.org (tick "Add to PATH").
2. In this folder: `pip install .`
3. Turn the printer on (hold power 3 s) and close the phone app (one connection at a time).
4. Run `ipreent scan` to see the name. Then it depends on the model:
   - **Bluetooth LE models** (GB01, X6, …): don't pair; ipreent connects directly.
   - **SC03h** (cat-face printer): works over BLE too (checked on hardware), so no pairing needed.
   - **Other serial models** (`Mini Printer`, X6H, … the app's `useSPP` flag): pair it in
     *Settings → Bluetooth & devices → Add device*. Windows creates a COM port
     (*More Bluetooth settings → COM Ports*, the "Outgoing" one). ipreent looks for it on its own,
     or pass it yourself:

```
ipreent -p COM5 -m SC03h text "hello"
```

After the first successful print the printer is remembered, so later commands connect directly.

```
ipreent scan                        # find printers, show model and connection type
ipreent print photo.jpg notes.txt   # images, PDFs, text files; several at once
ipreent print doc.pdf --pages 1-2   # PDF pages, scaled to the paper width
ipreent print qr.png --no-dither    # crisp black/white for QR codes and line art
ipreent text "Hello world"          # text from arguments...
echo "from a script" | ipreent text # ...or stdin
ipreent status --json               # state + battery, machine-readable
ipreent feed 100                    # feed blank paper
ipreent preview doc.pdf             # PNG of exactly what would print (no printer needed)
ipreent forget                      # forget the remembered printer
```
Options can go before or after the command (`ipreent text hi --ble`).
Common options: `-n 3` copies, `--size 40` bigger text, `--energy` darker/lighter, `--speed`.

### From Python
```python
import ipreent
ipreent.print_text("Build passed")
ipreent.print_file("label.pdf", copies=2)
print(ipreent.status())   # {'model': 'SC03h', 'state': 'ready', 'battery': 87}
```

Too light or too dark? Try `--energy 5000` (light) up to `--energy 17500` (dark), or a lower
`--speed`. If you see garbage instead of an image, try `--no-rle`.
If the name isn't recognized, it uses safe defaults (384 dots, uncompressed lines). Force a model with `-m GB03`.

## Layout
- `ipreent/protocol.py` – frames, CRC, line encoding (pure, tested against vendor bytes)
- `ipreent/models.py` + `models.json` – 187 model profiles taken from the vendor app
- `ipreent/imaging.py` – image/text → 1-bit rows
- `ipreent/ble.py` / `spp.py` – Bluetooth LE and Bluetooth serial transports
- `ipreent/api.py` – discovery, remembered printer, job building; `cli.py` on top
- `ipreent/convert.py` – file type detection, PDF rendering (pypdfium2)
- `tools/extract_models.py` – regenerate `models.json` from a jadx decompile

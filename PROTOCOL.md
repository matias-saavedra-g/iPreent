# iPrint mini printer protocol (reverse-engineered from com.frogtosea.iprint APK)

Source classes: `com.lib.blueUtils.{BluetoothOrder,PrintDataUtils,BluetoothUtils,PrinterModelUtils}`,
`com.Utils.PrintModelUtils` (model table), `com.lib.Utils.PrintEncoder` (key challenge).
This is the same family as the community "cat printer" (GB01/GB02/GB03/MX05/X6…).

## Transport
- BLE GATT. Service / write characteristic pairs (try in order):
  - `0000AE00-…` / write `0000AE01-…`, notify `0000AE04-…`  (most common)
  - `0000FF00-…` / write `0000FF02-…`, notify `0000FF03-…`
  - `0000AB00-…` / write `0000AB01-…`, notify `0000AB03-…`
  - extras: `0000AE80`/`AE81`, `49535343-FE7D-…`/`49535343-8841-…` (ISSC serial)
- Some models (`useSPP=true`) use classic Bluetooth SPP, UUID `00001101-0000-1000-8000-00805F9B34FB`.
- No flow-control characteristic: the app chunks to (MTU-3) bytes and sleeps `interval` ms (≈4–10) between writes.
- Printer is identified by BLE advertised name prefix (e.g. `GB01-xxxx`, `X6-xxxx`) → longest matching `modelNo`.

### SC03h (the cat-face printer, BLE name `SC03h-XXXX`)
`useSPP=true`: found by BLE name, but the app prints over classic SPP/RFCOMM (BLESPPUtils):
180-byte writes, ~4 ms apart, paused while the printer reports its buffer full.
Profile: 384 dots, 200 dpi, speed 10, energy 5000 (text 8000), RLE lines allowed. Gray mode available (energy 4100).

## Frame
```
51 78 CMD 00 LEN_LO LEN_HI DATA[LEN] CRC8(DATA) FF
```
CRC8 = poly 0x07, init 0 (table in BluetoothOrder.CHECKSUM_TABLE). "newFormat" models prefix every frame with `12`.

## Commands
| CMD | Name | Data |
|----|----|----|
| A1 | feed paper | u16 LE lines |
| A2 | bitmap line, raw | width/8 bytes, **LSB = leftmost pixel**, 1 = black |
| BF | bitmap line, RLE (models with `newCompress`) | bytes: bit7 = colour, bits0-6 = run length (≤127) |
| A3 | get device state | 00 → reply bitfield: b0 no paper, b1 cover open, b2 overheat, b3 low battery, b4 charging, b7 printing |
| A4 | quality / density | 0x31..0x35 (app uses 0x32/0x33/0x35) |
| A6 | lattice ctrl | start `AA 55 17 38 44 5F 5F 5F 44 38 2C`, end `AA 55 17 00…00 17` |
| A8 | get device info | 00 |
| AF | energy (heat) | u16 LE, e.g. GB01 8000/12000/17500 thin/mid/dark |
| B9 | battery | 00 |
| BB | device id read/write | |
| BD | speed / feed rate | u8 (≈10–35 depending on model) |
| BE | drawing mode | 00 image, 01 text, 02 tattoo, 03 label; 2-byte form for gray 8/16 level |
| D1 | XW key challenge (only models with `d1key`) | 8 random bytes, printer answers; see PrintEncoder |

## Print job (BW image, roll paper)
```
A4 quality → AF energy → BE mode → BD speed
for each line: A2 raw (or BF RLE if shorter); app re-sends BD every 200 lines
A1 feed 25 → A1 feed 48 ×2 (200dpi) / 72 (300dpi) → A3 get state
```
Image prep: grayscale → Floyd–Steinberg (images) or threshold (text), width = model `printSize` (384 for 58mm).

## Accounts / "activation" — what the lock actually is
- `ActiveDevRequest` / `AddDevRequest` / `GetDeviceIDRequest` POST the MAC to the vendor server.
  The reply only sets an **app-side** `CANPRINT` flag. The printer itself never gets anything from the server
  (except an optional device ID written with BB on some models). A standalone driver skips all of it.
- `d1key` models (e.g. GT09/GT10 key `23CCB36FC97F27B7`): purely local challenge/response, reproducible offline.

## Selected model parameters (modelNo, width px, dpi, imgSpeed, textSpeed, MTU, newCompress, interval, energy thin/mid/dark)
- GB01: 384, 200, 35, 25, 63, no, 6, 8000/12000/17500
- GB02: 384, 200, 26, 25, 83, no, 6, 8600/12000/16000
- GB03: 384, 200, 30, 10, 83, yes, 6, 7500
- X6:   384, 200, 30, 10, 123, yes, 6, 7500
- X6H:  384, 200, 10, 10, 180, yes, 4, 9500 (gray capable)
- GT08/09/10: 1728 (A4), 200, 30, 22, 383–512
Full table: `PrintModelUtils.java`, 196 `DataBean` entries.

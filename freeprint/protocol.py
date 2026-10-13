"""Wire protocol: frame building and bitmap encoding. Pure functions, no I/O.

Frame: 51 78 CMD 00 LEN_LO LEN_HI DATA CRC8(DATA) FF   (see PROTOCOL.md)
"""

CMD_FEED = 0xA1        # u16 LE: lines of blank paper
CMD_LINE_RAW = 0xA2    # width/8 bytes, LSB = leftmost pixel, 1 = black
CMD_GET_STATE = 0xA3
CMD_QUALITY = 0xA4
CMD_LATTICE = 0xA6
CMD_GET_INFO = 0xA8
CMD_FLOW = 0xAE        # sent BY the printer: data 0x10 = pause, 0x00 = resume
CMD_ENERGY = 0xAF      # u16 LE
CMD_BATTERY = 0xB9
CMD_SPEED = 0xBD       # u8
CMD_MODE = 0xBE        # 0 image, 1 text
CMD_LINE_RLE = 0xBF    # run-length encoded line

MODE_IMAGE = 0
MODE_TEXT = 1

LATTICE_START = bytes([0xAA, 0x55, 0x17, 0x38, 0x44, 0x5F, 0x5F, 0x5F, 0x44, 0x38, 0x2C])
LATTICE_END = bytes([0xAA, 0x55, 0x17, 0, 0, 0, 0, 0, 0, 0, 0x17])


def _make_crc8_table():
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if c & 0x80 else (c << 1) & 0xFF
        table.append(c)
    return table


_CRC8 = _make_crc8_table()


def crc8(data):
    c = 0
    for b in data:
        c = _CRC8[c ^ b]
    return c


def frame(cmd, data=b"\x00", new_format=False):
    data = bytes(data)
    out = bytes([0x51, 0x78, cmd, 0x00, len(data) & 0xFF, len(data) >> 8]) + data + bytes([crc8(data), 0xFF])
    return b"\x12" + out if new_format else out


def u16(v):
    return bytes([v & 0xFF, (v >> 8) & 0xFF])


def pack_row(row):
    """row: sequence of 0/1 pixels (1 = black), length divisible by 8."""
    out = bytearray(len(row) // 8)
    for i, px in enumerate(row):
        if px:
            out[i >> 3] |= 1 << (i & 7)
    return bytes(out)


def rle_row(row):
    """Run-length encode a row: each byte is (colour << 7) | run, run <= 127."""
    out = bytearray()
    i, n = 0, len(row)
    while i < n:
        colour = row[i]
        run = 1
        while i + run < n and row[i + run] == colour and run < 127:
            run += 1
        out.append((colour << 7) | run)
        i += run
    return bytes(out)


def line_frame(row, allow_rle, new_format=False):
    """Pick the shorter of raw and RLE encodings, like the vendor app does."""
    raw = pack_row(row)
    if allow_rle:
        rle = rle_row(row)
        if len(rle) < len(raw):
            return frame(CMD_LINE_RLE, rle, new_format)
    return frame(CMD_LINE_RAW, raw, new_format)


def print_job(rows, model, energy=None, speed=None, mode=MODE_IMAGE, quality=0x33, feed_after=None):
    """Build the full byte stream for one print. rows: list of 0/1 rows of model.width pixels."""
    nf = model.new_format
    speed = speed or (model.text_speed if mode == MODE_TEXT else model.img_speed)
    energy = model.energy if energy is None else energy
    feed_after = (72 if model.dpi == 300 else 48) * 2 if feed_after is None else feed_after

    out = bytearray(frame(CMD_QUALITY, [quality], nf))
    if energy:
        out += frame(CMD_ENERGY, u16(energy), nf)
    out += frame(CMD_MODE, [mode], nf)
    out += frame(CMD_SPEED, [speed], nf)
    out += frame(CMD_LATTICE, LATTICE_START, nf)
    for i, row in enumerate(rows):
        out += line_frame(row, model.rle, nf)
        if i and i % 200 == 0:
            out += frame(CMD_SPEED, [speed], nf)   # vendor app refreshes speed periodically
    out += frame(CMD_LATTICE, LATTICE_END, nf)
    out += frame(CMD_SPEED, [25], nf)
    if feed_after:
        out += frame(CMD_FEED, u16(feed_after), nf)
    out += frame(CMD_GET_STATE, b"\x00", nf)
    return bytes(out)


STATE_BITS = {0: "out of paper", 1: "cover open", 2: "overheated", 3: "low battery",
              4: "charging", 7: "printing"}


def parse_notification(data):
    """Split a notification into (cmd, payload) frames."""
    frames, i = [], 0
    while i + 6 <= len(data):
        if data[i] == 0x51 and data[i + 1] == 0x78:
            n = data[i + 4] | (data[i + 5] << 8)
            frames.append((data[i + 2], bytes(data[i + 6:i + 6 + n])))
            i += 8 + n
        else:
            i += 1
    return frames


def describe_state(payload):
    if not payload:
        return "unknown"
    flags = [name for bit, name in STATE_BITS.items() if payload[0] >> bit & 1]
    return ", ".join(flags) or "ready"

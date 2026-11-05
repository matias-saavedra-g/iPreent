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


def default_feed(dpi):
    """Blank lines fed after each print, as the vendor app does (two of its 'paper' feeds)."""
    return (72 if dpi == 300 else 48) * 2


# ---- how long a print takes ------------------------------------------------------------------
# The listing says "40 ppm", read at first as 40 mm/s, but real prints were far slower. Spec sheets
# for these 57 mm pocket printers say 10-15 mm/s, so the starting guess is 15 mm/s at the lightest
# heat (energy 5000, the vendor app's own setting for the SC03h). More heat means the head has to
# burn each line for longer, so until a darkness level has been timed its speed is scaled from the
# nearest timed level (or the guess) as if print time grew in proportion to the energy.
# Each finished print is timed and learnt for the energy it used (learn_speeds).
SPEC_MM_PER_S = 15.0
REF_ENERGY = 5000
CONNECT_S = 3.0          # Bluetooth connect + service discovery, once per job
COPY_OVERHEAD_S = 1.0    # waiting for the printer to report it has finished, per copy
MIN_MM_PER_S, MAX_MM_PER_S = 2.0, 100.0


def paper_mm(lines, dpi):
    return lines * 25.4 / dpi


def _clamp_speed(v):
    return min(MAX_MM_PER_S, max(MIN_MM_PER_S, v))


def speed_for(energy, learnt=None):
    """Paper speed in mm/s at `energy` (0/None = the printer's own default, taken as REF_ENERGY).

    learnt: {energy: mm/s} from timed prints. An energy with its own figure uses it; one between
    two learnt energies interpolates their seconds per mm; any other is scaled from the closest
    learnt energy (ties: the lower one), or from the starting guess.
    """
    energy = energy or REF_ENERGY
    learnt = learnt or {}
    if energy in learnt:
        return learnt[energy]
    below = [e for e in learnt if e < energy]
    above = [e for e in learnt if e > energy]
    if below and above:
        lo, hi = max(below), min(above)
        f = (energy - lo) / (hi - lo)
        return _clamp_speed(1 / ((1 - f) / learnt[lo] + f / learnt[hi]))
    if learnt:
        e0 = min(learnt, key=lambda e: (abs(e - energy), e))
        v0 = learnt[e0]
    else:
        e0, v0 = REF_ENERGY, SPEC_MM_PER_S
    return _clamp_speed(v0 * e0 / energy)


def estimate_seconds(lines, dpi=200, copies=1, mm_per_s=SPEC_MM_PER_S, feed=None, connect=True):
    """Seconds from pressing Print to the paper coming out, for `lines` rows of dots."""
    feed = default_feed(dpi) if feed is None else feed
    per_copy = paper_mm(lines + feed, dpi) / mm_per_s + COPY_OVERHEAD_S
    return (CONNECT_S if connect else 0.0) + max(1, copies) * per_copy


def measured_speed(lines, dpi, copies, seconds, feed=None):
    """mm/s shown by one timed print (connection excluded), or None if it can't tell.

    Short prints are mostly fixed overhead, so anything under 20 mm of paper is ignored.
    """
    feed = default_feed(dpi) if feed is None else feed
    mm = max(1, copies) * paper_mm(lines + feed, dpi)
    moving = seconds - max(1, copies) * COPY_OVERHEAD_S
    if mm < 20 or moving <= 0:
        return None
    return _clamp_speed(mm / moving)


def learn_speed(old, lines, dpi, copies, seconds, feed=None, alpha=0.3):
    """Blend one timed print (connection excluded) into the known speed in mm/s."""
    measured = measured_speed(lines, dpi, copies, seconds, feed)
    return old if measured is None else old + alpha * (measured - old)


def learn_speeds(learnt, energy, lines, dpi, copies, seconds, feed=None):
    """New {energy: mm/s} after one timed print at `energy`.

    The first timed print at an energy replaces the guess; later ones are blended in (30 %).
    """
    energy = energy or REF_ENERGY
    learnt = dict(learnt or {})
    measured = measured_speed(lines, dpi, copies, seconds, feed)
    if measured is not None:
        old = learnt.get(energy)
        learnt[energy] = measured if old is None else old + 0.3 * (measured - old)
    return learnt


def format_eta(seconds):
    """0:07, 1:30, 12:05: rounded up, so a countdown never shows 0:00 before it's done."""
    s = max(0, int(-(-seconds // 1)))
    return f"{s // 60}:{s % 60:02d}"


def print_job(rows, model, energy=None, speed=None, mode=MODE_IMAGE, quality=0x33, feed_after=None):
    """Build the full byte stream for one print. rows: list of 0/1 rows of model.width pixels."""
    nf = model.new_format
    speed = speed or (model.text_speed if mode == MODE_TEXT else model.img_speed)
    energy = model.energy if energy is None else energy
    feed_after = default_feed(model.dpi) if feed_after is None else feed_after

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

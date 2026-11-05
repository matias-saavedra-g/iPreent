"""Check frame building against byte arrays hard-coded in the vendor app (BluetoothOrder.java)."""
from ipreent import protocol as p


def b(*vals):
    return bytes(v & 0xFF for v in vals)


def test_frames_match_vendor_constants():
    assert p.frame(0xA4, [0x33]) == b(81, 120, -92, 0, 1, 0, 51, -103, -1)          # quality3
    assert p.frame(0xA1, p.u16(48)) == b(81, 120, -95, 0, 2, 0, 48, 0, -7, -1)        # paper
    assert p.frame(0xA1, p.u16(72)) == b(81, 120, -95, 0, 2, 0, 72, 0, -13, -1)       # paper_300dpi
    assert p.frame(0xBE, [1]) == b(81, 120, -66, 0, 1, 0, 1, 7, -1)                   # print_text
    assert p.frame(0xA6, p.LATTICE_END) == b(81, 120, -90, 0, 11, 0, -86, 85, 23, 0, 0, 0, 0, 0, 0, 0, 23, 17, -1)
    assert p.frame(0xA8, b"\x00", new_format=True) == b(18, 81, 120, -88, 0, 1, 0, 0, 0, -1)


def test_row_encodings():
    row = [1] + [0] * 7 + [0] * 376
    assert p.pack_row(row)[0] == 0x01                 # leftmost pixel = LSB
    assert p.rle_row([0] * 384) == bytes([127, 127, 127, 3])
    assert p.rle_row([1] * 3 + [0] * 5) == bytes([0x83, 0x05])
    assert p.line_frame([0] * 384, allow_rle=True)[2] == 0xBF
    assert p.line_frame([0] * 384, allow_rle=False)[2] == 0xA2


def test_notification_parse():
    data = p.frame(0xA3, b"\x01") + p.frame(0xAE, b"\x10")
    assert p.parse_notification(data) == [(0xA3, b"\x01"), (0xAE, b"\x10")]
    assert p.describe_state(b"\x01") == "out of paper"


def test_print_time_estimate():
    # 400 lines + 96 feed at 200 dpi = 62.99 mm; at 40 mm/s = 1.575 s, +1 s per copy, +3 s connect.
    assert round(p.estimate_seconds(400, 200), 3) == 5.575
    assert round(p.estimate_seconds(400, 200, copies=2, connect=False), 3) == 5.150
    assert round(p.estimate_seconds(0, 200, mm_per_s=20), 3) == 4.610
    assert p.estimate_seconds(400, 200, copies=0) == p.estimate_seconds(400, 200)


def test_learn_speed():
    # 1600 + 96 lines = 215.39 mm took 11 s (10 s moving): measured 21.54 mm/s, blended 30% into 40.
    assert round(p.learn_speed(40.0, 1600, 200, 1, 11.0), 3) == 34.462
    assert p.learn_speed(40.0, 10, 200, 1, 9.0) == 40.0          # too short to tell
    assert p.learn_speed(40.0, 1600, 200, 1, 0.5) == 40.0        # nonsense timing
    assert p.learn_speed(40.0, 1600, 200, 1, 1000.0) == 40.0 + 0.3 * (5.0 - 40.0)   # clamped


def test_format_eta():
    assert [p.format_eta(s) for s in (0, 0.2, 7, 59.5, 90, 725)] == ["0:00", "0:01", "0:07", "1:00", "1:30", "12:05"]

"""Check frame building against byte arrays hard-coded in the vendor app (BluetoothOrder.java)."""
from freeprint import protocol as p


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

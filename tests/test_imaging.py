import pytest

from PIL import Image

from ipreent import imaging


def test_dither_methods_keep_size_and_tone():
    g = imaging.gray(Image.new("L", (200, 100), 128), 384, auto_rotate=False)
    for m in imaging.DITHERS:
        rows = imaging.bw_rows(g, m)
        assert len(rows) == 192 and all(len(r) == 384 for r in rows)
        black = sum(map(sum, rows)) / (384 * 192)
        if m != "threshold":
            assert 0.35 < black < 0.65, m


def test_trim_crops_margins_and_skips_blank_pages():
    page = Image.new("L", (600, 800), 255)
    page.paste(0, (100, 200, 300, 260))
    t = imaging.trim(page, pad=0)
    assert t.size == (200, 60)
    assert imaging.trim(Image.new("L", (50, 50), 255)) is None


def test_generated_pictures_fit_the_paper():
    for img in (imaging.checklist_image("T", ["a", "b"], 384), imaging.banner_image("Hi", 384),
                imaging.qr_image("https://example.com", 384)):
        assert img.width == 384


def test_code128_patterns_are_11_modules():
    assert all(sum(map(int, p)) == 11 for p in imaging._C128)
    assert len(imaging._C128) == 106


def test_code128_known_encoding():
    # "PJJ123C" from the Code 128 Wikipedia example: checksum value 54
    mods = imaging.code128("PJJ123C")
    assert len(mods) == 11 * 9 + 13
    assert imaging.code128("1234")[:11] == [1, 1, 0, 1, 0, 0, 1, 1, 1, 0, 0]     # start C


def test_barcode_image_and_errors():
    img = imaging.barcode_image("ABC-123", 384)
    assert img.width == 384
    with pytest.raises(ValueError):
        imaging.code128("café")
    with pytest.raises(ValueError):
        imaging.barcode_image("X" * 200, 384)


def test_emoji_text_uses_emoji_font():
    runs = imaging._runs("hi 👍🏽 ok", 28)
    if imaging._fallbacks(28):
        assert [t for t, _ in runs] == ["hi ", "👍🏽", " ok"]
    assert imaging.text_image("hi 👍 ❤️ 👨‍👩‍👧", 384).getbbox() is not None

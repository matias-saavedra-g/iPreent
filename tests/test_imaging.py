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

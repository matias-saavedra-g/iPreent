"""Ruler: the same cases as android/app/src/test/java/com/ipreent/RulerTest.kt (keep them in step)."""
from ipreent import protocol, ruler


def summary(rows):
    """Height, black dots and a hash of where they are: the Kotlin port must give the same three numbers."""
    black, h = 0, 0
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            if v:
                black += 1
                h = (h * 31 + y * 1009 + x) % 1000000007
    return len(rows), black, h


def test_dots_per_mm():
    assert protocol.dots_per_mm(200) == 8.0                  # the vendor's "200 dpi" is 203.2 dpi
    assert round(protocol.dots_per_mm(300), 4) == 11.811
    assert protocol.paper_mm(800, 200) == 100.0


def test_ticks_are_rounded_one_by_one():
    lay = ruler.Layout(384, 200, 100)
    assert [lay.tick(mm) for mm in (0, 1, 10, 100)] == [58, 66, 138, 858]
    assert lay.height() == 924
    # Every mark within half a row of its exact place, however long the ruler: no error builds up.
    lay = ruler.Layout(384, 200, 1000, 98.5)
    for mm in range(0, 1001):
        exact = lay.origin + mm * lay.k
        assert abs(lay.tick(mm) - exact) <= 0.5


def test_feed_correction():
    # A printed 100 mm measured 98.5 mm: the paper moves 1.5 % less per row, so rows are spread out.
    lay = ruler.Layout(384, 200, 100, 98.5)
    assert [lay.tick(mm) for mm in (0, 1, 10, 100)] == [58, 66, 139, 870]
    assert lay.height() == 936


def test_limits():
    assert ruler.Layout(384, 200, 5).length == 10 and ruler.Layout(384, 200, 5000).length == 1000
    assert ruler.clamp_measured(50) == 90.0 and ruler.clamp_measured(150) == 110.0
    assert ruler.clamp_measured("x") == ruler.clamp_measured(float("nan")) == 100.0


def test_same_dots_as_android():
    assert summary(ruler.rows(384, 200, 100)) == (924, 35147, 602050560)
    assert summary(ruler.rows(384, 200, 25, 98.5)) == (327, 11727, 991820111)
    lay = ruler.Layout(576, 300, 50)                       # 300 dpi: sizes scale, still mm accurate
    assert (lay.thick, lay.origin, lay.tick(10), lay.tick(50)) == (3, 86, 204, 677)
    assert summary(ruler.rows(576, 300, 50)) == (774, 42189, 186042080)


def test_image_prints_exactly_the_rows():
    from ipreent import api
    rows, mode = api.rows_for([(ruler.image(384, 200, 20), True)], 384, dither=False)
    assert rows == ruler.rows(384, 200, 20) and mode == protocol.MODE_TEXT

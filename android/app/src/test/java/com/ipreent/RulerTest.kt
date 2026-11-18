package com.ipreent

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Same cases as tests/test_ruler.py: keep them in step. */
class RulerTest {
    /** Height, black dots and a hash of where they are: the Python twin must give the same three numbers. */
    private fun summary(rows: List<ByteArray>): Triple<Int, Int, Long> {
        var black = 0
        var h = 0L
        rows.forEachIndexed { y, row ->
            row.forEachIndexed { x, v ->
                if (v.toInt() != 0) { black++; h = (h * 31 + y * 1009 + x) % 1000000007L }
            }
        }
        return Triple(rows.size, black, h)
    }

    @Test fun dotsPerMm() {
        assertEquals(8.0, Protocol.dotsPerMm(200), 0.0)
        assertEquals(11.811, Protocol.dotsPerMm(300), 1e-3)
        assertEquals(100.0, Protocol.paperMm(800, 200), 0.0)
    }

    @Test fun ticksAreRoundedOneByOne() {
        val lay = Ruler.Layout(384, 200, 100)
        assertEquals(listOf(58, 66, 138, 858), listOf(0, 1, 10, 100).map { lay.tick(it) })
        assertEquals(924, lay.height())
        val long = Ruler.Layout(384, 200, 1000, 98.5)
        for (mm in 0..1000) assertTrue(Math.abs(long.tick(mm) - (long.origin + mm * long.k)) <= 0.5)
    }

    @Test fun feedCorrection() {
        val lay = Ruler.Layout(384, 200, 100, 98.5)
        assertEquals(listOf(58, 66, 139, 870), listOf(0, 1, 10, 100).map { lay.tick(it) })
        assertEquals(936, lay.height())
    }

    @Test fun limits() {
        assertEquals(10, Ruler.Layout(384, 200, 5).length)
        assertEquals(1000, Ruler.Layout(384, 200, 5000).length)
        assertEquals(90.0, Ruler.clampMeasured(50.0), 0.0)
        assertEquals(110.0, Ruler.clampMeasured(150.0), 0.0)
        assertEquals(100.0, Ruler.clampMeasured(Double.NaN), 0.0)
        assertEquals(100.0, Ruler.clampMeasured(null), 0.0)
    }

    @Test fun sameDotsAsPython() {
        assertEquals(Triple(924, 35147, 602050560L), summary(Ruler.rows(384, 200, 100)))
        assertEquals(Triple(327, 11727, 991820111L), summary(Ruler.rows(384, 200, 25, 98.5)))
        val lay = Ruler.Layout(576, 300, 50)
        assertEquals(listOf(3, 86, 204, 677), listOf(lay.thick, lay.origin, lay.tick(10), lay.tick(50)))
        assertEquals(Triple(774, 42189, 186042080L), summary(Ruler.rows(576, 300, 50)))
    }
}

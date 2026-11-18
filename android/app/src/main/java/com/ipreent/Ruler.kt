package com.ipreent

/**
 * A millimetre ruler printed along the paper, for measuring things and for timing the printer on video.
 * Line-by-line port of ipreent/ruler.py (read its docstring for the accuracy notes): plain geometry with
 * seven-segment digits and no fonts, so the phone prints exactly the same dots as the PC. RulerTest.kt and
 * tests/test_ruler.py check the same numbers.
 */
object Ruler {
    const val DEFAULT_MM = 100
    const val MIN_MM = 10
    const val MAX_MM = 1000
    const val DEFAULT_MEASURED = 100.0     // what a printed 100 mm measured: 100 = no correction
    const val MIN_MEASURED = 90.0
    const val MAX_MEASURED = 110.0

    /** Seven segments: a top, b top right, c bottom right, d bottom, e bottom left, f top left, g middle. */
    private val SEGMENTS = listOf("abcdef", "bc", "abged", "abgcd", "fgbc", "afgcd", "afgedc", "abc", "abcdefg", "abcdfg")

    private fun halfUp(v: Double): Int = Math.floor(v + 0.5).toInt()

    fun clampLength(mm: Int) = mm.coerceIn(MIN_MM, MAX_MM)

    fun clampMeasured(v: Double?): Double =
        if (v == null || v.isNaN()) DEFAULT_MEASURED else v.coerceIn(MIN_MEASURED, MAX_MEASURED)

    /** Paper rows per real millimetre, after the feed correction. */
    fun rowsPerMm(dpi: Int, measured: Double = DEFAULT_MEASURED) = Protocol.dotsPerMm(dpi) * 100.0 / clampMeasured(measured)

    private class Canvas(val w: Int, val h: Int) {
        val px = List(h) { ByteArray(w) }

        /** Black rectangle [x0, x1) × [y0, y1), clipped to the canvas. */
        fun fill(x0: Int, y0: Int, x1: Int, y1: Int) {
            val a = maxOf(0, x0); val b = minOf(w, x1)
            for (y in maxOf(0, y0) until minOf(h, y1)) if (b > a) px[y].fill(1, a, b)
        }

        fun digit(d: Int, x: Int, y: Int, w: Int, h: Int, s: Int) {
            val segs = SEGMENTS[d]
            val mid = y + (h - s) / 2
            val half = y + h / 2
            if ('a' in segs) fill(x, y, x + w, y + s)
            if ('d' in segs) fill(x, y + h - s, x + w, y + h)
            if ('g' in segs) fill(x, mid, x + w, mid + s)
            if ('f' in segs) fill(x, y, x + s, half + s / 2)
            if ('b' in segs) fill(x + w - s, y, x + w, half + s / 2)
            if ('e' in segs) fill(x, half - s / 2, x + s, y + h)
            if ('c' in segs) fill(x + w - s, half - s / 2, x + w, y + h)
        }

        /** n centred on (cx, cy). */
        fun number(n: Int, cx: Int, cy: Int, w: Int, h: Int, s: Int, gap: Int) {
            val text = n.toString()
            val total = text.length * w + (text.length - 1) * gap
            val x = cx - total / 2
            text.forEachIndexed { i, ch -> digit(ch - '0', x + i * (w + gap), cy - h / 2, w, h, s) }
        }
    }

    /** Where everything goes, in dots and rows; sizes scale so they stay the same in mm on 300 dpi printers. */
    class Layout(val width: Int, dpi: Int, lengthMm: Int = DEFAULT_MM, measured: Double = DEFAULT_MEASURED) {
        val dpmm = Protocol.dotsPerMm(dpi)
        val length = clampLength(lengthMm)
        val k = rowsPerMm(dpi, measured)
        private val s = dpmm / 8.0
        fun r(v: Int) = maxOf(1, halfUp(v * s))
        val thick = r(2)                          // every tick and line is 2 dots (1/4 mm) thick
        val top = r(8)                            // the scale across the paper starts here
        val origin = top + thick + r(48)          // row of the 0 mm line of the ruler along the paper
        val bottom = r(64)                        // room for the last number, under the end line

        /** Top row of the tick at [mm] along the paper (each one rounded on its own). */
        fun tick(mm: Int) = origin + halfUp(mm * k)

        fun height() = tick(length) + thick + bottom
    }

    /** The ruler as rows of 0/1 dots (1 = black), [width] dots wide. */
    fun rows(width: Int, dpi: Int, lengthMm: Int = DEFAULT_MM, measured: Double = DEFAULT_MEASURED): List<ByteArray> {
        val lay = Layout(width, dpi, lengthMm, measured)
        val t = lay.thick
        val w = width
        val c = Canvas(w, lay.height())
        fun r(v: Int) = lay.r(v)

        // Across the paper: a baseline with a tick every mm (longer every 5 and 10), numbered in cm.
        val y = lay.top
        c.fill(0, y, w, y + t)
        var mm = 0
        while (true) {
            var x = halfUp(mm * lay.dpmm)
            if (x > w - 1) break
            x = minOf(x, w - t)
            val long = if (mm % 10 == 0) r(32) else if (mm % 5 == 0) r(20) else r(12)
            c.fill(x, y + t, x + t, y + t + long)
            if (mm % 10 == 0 && x + r(4) + r(10) <= w) c.digit(mm / 10 % 10, x + r(4), y + t + r(14), r(10), r(16), r(2))
            mm++
        }

        // Along the paper: ticks on both edges, a full line at 0 and at the end, numbers every cm,
        // a dashed guide across at every cm and the timing track (blocks switching every mm).
        val short = r(24); val mid = r(40); val long = r(64)
        val t0 = r(72); val t1 = r(88)
        val dw = r(26); val dh = r(44); val ds = r(5); val gap = r(8)
        for (m in 0..lay.length) {
            val p = lay.tick(m)
            if (m == 0 || m == lay.length) c.fill(0, p, w, p + t)
            else {
                val n = if (m % 10 == 0) long else if (m % 5 == 0) mid else short
                c.fill(0, p, n, p + t)
                c.fill(w - n, p, w, p + t)
            }
            if (m < lay.length && m % 2 == 0) {
                val q = lay.tick(m + 1)
                c.fill(t0, p, t1, q)
                c.fill(w - t1, p, w - t0, q)
            }
            if (m % 10 == 0) {                    // the number sits just under its tick, like a tape measure
                c.number(m / 10, w / 2, p + t + r(6) + dh / 2, dw, dh, ds, gap)
                if (m in 1 until lay.length) {
                    val x0 = t1 + r(8); val x1 = w - t1 - r(8)
                    var x = x0
                    while (x < x1) { c.fill(x, p, minOf(x + r(4), x1), p + 1); x += r(8) }
                }
            }
        }
        return c.px
    }
}

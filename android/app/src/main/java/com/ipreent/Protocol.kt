package com.ipreent

import java.io.ByteArrayOutputStream

/** Wire protocol: frame building and bitmap encoding. Pure functions, no I/O. Port of ipreent/protocol.py.
 *
 * Frame: 51 78 CMD 00 LEN_LO LEN_HI DATA CRC8(DATA) FF   (see PROTOCOL.md)
 */
object Protocol {
    const val CMD_FEED = 0xA1
    const val CMD_LINE_RAW = 0xA2
    const val CMD_GET_STATE = 0xA3
    const val CMD_QUALITY = 0xA4
    const val CMD_LATTICE = 0xA6
    const val CMD_FLOW = 0xAE      // sent BY the printer: data 0x10 = pause, 0x00 = resume
    const val CMD_ENERGY = 0xAF
    const val CMD_BATTERY = 0xB9
    const val CMD_SPEED = 0xBD
    const val CMD_MODE = 0xBE
    const val CMD_LINE_RLE = 0xBF

    const val MODE_IMAGE = 0
    const val MODE_TEXT = 1

    val LATTICE_START = bytes(0xAA, 0x55, 0x17, 0x38, 0x44, 0x5F, 0x5F, 0x5F, 0x44, 0x38, 0x2C)
    val LATTICE_END = bytes(0xAA, 0x55, 0x17, 0, 0, 0, 0, 0, 0, 0, 0x17)

    private val CRC8 = IntArray(256) { i ->
        var c = i
        repeat(8) { c = if (c and 0x80 != 0) ((c shl 1) xor 0x07) and 0xFF else (c shl 1) and 0xFF }
        c
    }

    fun bytes(vararg v: Int) = ByteArray(v.size) { v[it].toByte() }

    fun crc8(data: ByteArray): Int {
        var c = 0
        for (b in data) c = CRC8[c xor (b.toInt() and 0xFF)]
        return c
    }

    fun frame(cmd: Int, data: ByteArray = bytes(0), newFormat: Boolean = false): ByteArray {
        val out = ByteArrayOutputStream(data.size + 9)
        if (newFormat) out.write(0x12)
        out.write(bytes(0x51, 0x78, cmd, 0, data.size and 0xFF, data.size shr 8))
        out.write(data)
        out.write(crc8(data))
        out.write(0xFF)
        return out.toByteArray()
    }

    fun u16(v: Int) = bytes(v and 0xFF, (v shr 8) and 0xFF)

    /** row: one byte per pixel (1 = black), length divisible by 8. Leftmost pixel = LSB. */
    fun packRow(row: ByteArray): ByteArray {
        val out = ByteArray(row.size / 8)
        for (i in row.indices) if (row[i].toInt() != 0) out[i shr 3] = (out[i shr 3].toInt() or (1 shl (i and 7))).toByte()
        return out
    }

    /** Each byte is (colour << 7) | run, run <= 127. */
    fun rleRow(row: ByteArray): ByteArray {
        val out = ByteArrayOutputStream()
        var i = 0
        while (i < row.size) {
            val colour = row[i].toInt()
            var run = 1
            while (i + run < row.size && row[i + run].toInt() == colour && run < 127) run++
            out.write((colour shl 7) or run)
            i += run
        }
        return out.toByteArray()
    }

    /** Pick the shorter of raw and RLE encodings, like the vendor app does. */
    fun lineFrame(row: ByteArray, allowRle: Boolean, newFormat: Boolean = false): ByteArray {
        val raw = packRow(row)
        if (allowRle) {
            val rle = rleRow(row)
            if (rle.size < raw.size) return frame(CMD_LINE_RLE, rle, newFormat)
        }
        return frame(CMD_LINE_RAW, raw, newFormat)
    }

    /** Blank lines fed after each print, as the vendor app does (two of its 'paper' feeds). */
    fun defaultFeed(dpi: Int) = (if (dpi == 300) 72 else 48) * 2

    // ---- how long a print takes (port of the same block in protocol.py) ----
    /** Starting guess: 15 mm/s at the lightest heat (spec sheets of these printers say 10-15 mm/s; the
     *  listing's "40 ppm" was far too fast). Darker levels start slower, in proportion to the energy. */
    const val SPEC_MM_PER_S = 15.0
    const val REF_ENERGY = 5000
    const val CONNECT_S = 3.0
    const val COPY_OVERHEAD_S = 1.0
    const val MIN_MM_PER_S = 2.0
    const val MAX_MM_PER_S = 100.0

    fun paperMm(lines: Int, dpi: Int) = lines * 25.4 / dpi

    /** Paper speed at [energy] (0 = the printer's default, taken as [REF_ENERGY]). A learnt energy uses its
     *  figure; one between two learnt energies interpolates their seconds per mm; any other is scaled from
     *  the closest learnt energy (ties: the lower one), or from the starting guess. */
    fun speedFor(energy: Int, learnt: Map<Int, Double> = emptyMap()): Double {
        val e = if (energy == 0) REF_ENERGY else energy
        learnt[e]?.let { return it }
        val lo = learnt.keys.filter { it < e }.maxOrNull()
        val hi = learnt.keys.filter { it > e }.minOrNull()
        if (lo != null && hi != null) {
            val f = (e - lo).toDouble() / (hi - lo)
            return (1 / ((1 - f) / learnt.getValue(lo) + f / learnt.getValue(hi))).coerceIn(MIN_MM_PER_S, MAX_MM_PER_S)
        }
        val e0 = learnt.keys.minWithOrNull(compareBy<Int>({ kotlin.math.abs(it - e) }, { it })) ?: REF_ENERGY
        val v0 = learnt[e0] ?: SPEC_MM_PER_S
        return (v0 * e0 / e).coerceIn(MIN_MM_PER_S, MAX_MM_PER_S)
    }

    /** Seconds from pressing Print to the paper coming out, for [lines] rows of dots. */
    fun estimateSeconds(lines: Int, dpi: Int = 200, copies: Int = 1, mmPerS: Double = SPEC_MM_PER_S,
                        feed: Int? = null, connect: Boolean = true): Double {
        val perCopy = paperMm(lines + (feed ?: defaultFeed(dpi)), dpi) / mmPerS + COPY_OVERHEAD_S
        return (if (connect) CONNECT_S else 0.0) + maxOf(1, copies) * perCopy
    }

    /** mm/s shown by one timed print (connection excluded), or null if under 20 mm or nonsense. */
    fun measuredSpeed(lines: Int, dpi: Int, copies: Int, seconds: Double, feed: Int? = null): Double? {
        val mm = maxOf(1, copies) * paperMm(lines + (feed ?: defaultFeed(dpi)), dpi)
        val moving = seconds - maxOf(1, copies) * COPY_OVERHEAD_S
        if (mm < 20 || moving <= 0) return null
        return (mm / moving).coerceIn(MIN_MM_PER_S, MAX_MM_PER_S)
    }

    /** Blend one timed print (connection excluded) into the known speed. */
    fun learnSpeed(old: Double, lines: Int, dpi: Int, copies: Int, seconds: Double, feed: Int? = null, alpha: Double = 0.3): Double {
        val measured = measuredSpeed(lines, dpi, copies, seconds, feed) ?: return old
        return old + alpha * (measured - old)
    }

    /** Speeds per energy after one timed print at [energy]: the first replaces the guess, later ones blend 30 %. */
    fun learnSpeeds(learnt: Map<Int, Double>, energy: Int, lines: Int, dpi: Int, copies: Int, seconds: Double,
                    feed: Int? = null): Map<Int, Double> {
        val e = if (energy == 0) REF_ENERGY else energy
        val measured = measuredSpeed(lines, dpi, copies, seconds, feed) ?: return learnt
        val old = learnt[e]
        return learnt + (e to if (old == null) measured else old + 0.3 * (measured - old))
    }

    /** 0:07, 1:30, 12:05; rounded up so a countdown never shows 0:00 before it's done. */
    fun formatEta(seconds: Double): String {
        val s = maxOf(0, kotlin.math.ceil(seconds).toInt())
        return "%d:%02d".format(s / 60, s % 60)
    }

    fun printJob(rows: List<ByteArray>, model: Model, energy: Int? = null, mode: Int = MODE_IMAGE,
                 quality: Int = 0x33, feedAfter: Int? = null): ByteArray {
        val nf = model.newFormat
        val speed = if (mode == MODE_TEXT) model.textSpeed else model.imgSpeed
        val e = energy ?: model.energy
        val feed = feedAfter ?: defaultFeed(model.dpi)
        val out = ByteArrayOutputStream()
        out.write(frame(CMD_QUALITY, bytes(quality), nf))
        if (e != 0) out.write(frame(CMD_ENERGY, u16(e), nf))
        out.write(frame(CMD_MODE, bytes(mode), nf))
        out.write(frame(CMD_SPEED, bytes(speed), nf))
        out.write(frame(CMD_LATTICE, LATTICE_START, nf))
        rows.forEachIndexed { i, row ->
            out.write(lineFrame(row, model.rle, nf))
            if (i != 0 && i % 200 == 0) out.write(frame(CMD_SPEED, bytes(speed), nf))
        }
        out.write(frame(CMD_LATTICE, LATTICE_END, nf))
        out.write(frame(CMD_SPEED, bytes(25), nf))
        if (feed != 0) out.write(frame(CMD_FEED, u16(feed), nf))
        out.write(frame(CMD_GET_STATE, bytes(0), nf))
        return out.toByteArray()
    }

    private val STATE_BITS = mapOf(0 to "out of paper", 1 to "cover open", 2 to "overheated",
        3 to "low battery", 4 to "charging", 7 to "printing")

    /** Split a notification into (cmd, payload) frames. */
    fun parseNotification(data: ByteArray): List<Pair<Int, ByteArray>> {
        val frames = mutableListOf<Pair<Int, ByteArray>>()
        var i = 0
        while (i + 6 <= data.size) {
            if (data[i] == 0x51.toByte() && data[i + 1] == 0x78.toByte()) {
                val n = (data[i + 4].toInt() and 0xFF) or ((data[i + 5].toInt() and 0xFF) shl 8)
                frames += (data[i + 2].toInt() and 0xFF) to data.copyOfRange(i + 6, minOf(data.size, i + 6 + n))
                i += 8 + n
            } else i++
        }
        return frames
    }

    fun describeState(payload: ByteArray?): String {
        if (payload == null || payload.isEmpty()) return "unknown"
        val b = payload[0].toInt() and 0xFF
        return STATE_BITS.filter { (bit, _) -> b shr bit and 1 == 1 }.values.joinToString(", ").ifEmpty { "ready" }
    }
}

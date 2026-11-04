package com.ipreent

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import com.google.zxing.oned.Code128Writer
import java.math.BigDecimal
import java.math.RoundingMode
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

const val DEFAULT_FOOTER = "Thank you for your purchase!"

/** Money and quantities for receipts, in Chilean pesos. Port of ipreent/receipt.py (pure, unit-tested). */
object Clp {
    /** "$12.990", "12990", "12,990", "-1.000" → whole pesos. A separator followed by 1–2 digits at the end is decimals. */
    fun parsePrice(text: String): Long {
        val t = text.trim()
        val neg = '-' in t.takeWhile { !it.isDigit() }
        val body = t.filter { it.isDigit() || it == '.' || it == ',' }
        require(body.any { it.isDigit() }) { "not a price: \"$text\"" }
        val cents = Regex("[.,](\\d{1,2})$").find(body)
        val whole = (if (cents != null) body.substring(0, cents.range.first) else body).filter { it.isDigit() }.ifEmpty { "0" }
        var amount = BigDecimal(whole)
        if (cents != null) amount += BigDecimal("0." + cents.groupValues[1])
        return round(if (neg) amount.negate() else amount)
    }

    /** "2", "1,5", "1.5", "x3", "" (= 1) → quantity above zero. */
    fun parseQty(text: String): BigDecimal {
        val t = text.lowercase().filterNot { it == 'x' || it == '×' || it.isWhitespace() }.replace(',', '.')
        val q = if (t.isEmpty()) BigDecimal.ONE else t.toBigDecimalOrNull() ?: throw IllegalArgumentException("not a quantity: \"$text\"")
        require(q.signum() > 0) { "quantity must be more than zero" }
        return q
    }

    fun round(d: BigDecimal): Long = d.setScale(0, RoundingMode.HALF_UP).toLong()

    /** 12990 → "$12.990", -1000 → "-$1.000". */
    fun format(amount: Long): String {
        val digits = Math.abs(amount).toString().reversed().chunked(3).joinToString(".").reversed()
        return (if (amount < 0) "-" else "") + "$" + digits
    }

    /** 2 → "2", 1.50 → "1,5". */
    fun qty(q: BigDecimal): String {
        val n = q.stripTrailingZeros()
        return (if (n.scale() < 0) n.setScale(0) else n).toPlainString().replace('.', ',')
    }
}

data class ReceiptItem(val name: String, val price: Long, val qty: BigDecimal = BigDecimal.ONE) {
    val amount get() = Clp.round(qty * BigDecimal(price))
}

/** The receipt number is the print time (YYMMDDhhmmss): no counter to store or sync between devices. */
class Receipt(
    val business: String, val address: String, val url: String, items: List<ReceiptItem>,
    val footer: String = DEFAULT_FOOTER, val time: Date = Date(),
    val number: String = SimpleDateFormat("yyMMddHHmmss", Locale.US).format(time),
) {
    val items = items.filter { it.name.isNotBlank() }
    val total get() = items.sumOf { it.amount }
    /** Units sold; with weighed products (1,5 kg) it counts lines instead. */
    val count: String get() =
        if (items.all { it.qty.stripTrailingZeros().scale() <= 0 }) items.sumOf { it.qty }.toBigInteger().toString()
        else items.size.toString()

    companion object {
        /** From the editor's text fields; throws with a readable message ("Row 2: no price"). */
        fun fromRows(business: String, address: String, url: String, footer: String, rows: List<Triple<String, String, String>>): Receipt {
            val items = rows.filter { (n, _, p) -> n.isNotBlank() || p.isNotBlank() }.mapIndexed { i, (name, qty, price) ->
                try {
                    require(name.isNotBlank()) { "no product name" }
                    require(price.isNotBlank()) { "no price" }
                    ReceiptItem(name.trim(), Clp.parsePrice(price), Clp.parseQty(qty))
                } catch (e: IllegalArgumentException) {
                    throw IllegalArgumentException("Row ${i + 1}: ${e.message}")
                }
            }
            require(items.isNotEmpty()) { "Add products with their quantity and price." }
            return Receipt(business, address, url, items, footer)
        }
    }
}

/** Draws a receipt the same way as ipreent/receipt.py: header, products, big total, footer, Code 128 barcode. */
object ReceiptArt {
    private class Sheet(val w: Int) {
        var y = 0f
        val ops = mutableListOf<(Canvas) -> Unit>()
        fun text(s: String, p: Paint, align: Char, margin: Float = 0f) {
            val tw = p.measureText(s)
            val x = when (align) { 'c' -> (w - tw) / 2; 'r' -> w - margin - tw; else -> margin }
            val base = y - p.fontMetrics.ascent
            ops += { it.drawText(s, x, base, p) }
        }
        fun rect(l: Float, t: Float, r: Float, b: Float) {
            ops += { it.drawRect(l, t, r, b, fill) }
        }
        fun bitmap(): Bitmap {
            val bmp = Bitmap.createBitmap(w, maxOf(1, Math.round(y)), Bitmap.Config.ARGB_8888)
            val c = Canvas(bmp).apply { drawColor(Color.WHITE) }
            ops.forEach { it(c) }
            return bmp
        }
        companion object { val fill = Paint().apply { color = Color.BLACK; style = Paint.Style.FILL } }
    }

    private fun paint(size: Float, face: Typeface) = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.BLACK; textSize = size; typeface = face
    }

    /** Lines of [text] that fit [maxW]; very long words are cut. */
    private fun wrap(text: String, p: Paint, maxW: Float): List<String> {
        val out = mutableListOf<String>()
        for (para in text.lines()) {
            var cur = ""
            for (w0 in para.split(' ').filter { it.isNotEmpty() }) {
                var word = w0
                val trial = if (cur.isEmpty()) word else "$cur $word"
                if (p.measureText(trial) <= maxW) { cur = trial; continue }
                if (cur.isNotEmpty()) out += cur
                while (word.length > 1 && p.measureText(word) > maxW) {
                    var n = word.length - 1
                    while (n > 1 && p.measureText(word, 0, n) > maxW) n--
                    out += word.substring(0, n)
                    word = word.substring(n)
                }
                cur = word
            }
            if (cur.isNotEmpty()) out += cur
        }
        return out
    }

    fun bitmap(r: Receipt, width: Int): Bitmap {
        val k = width / 384f                      // sizes are for 58 mm paper (384 dots)
        fun px(v: Float) = maxOf(1f, Math.round(v * k).toFloat())
        val m = px(6f)
        val mono = Typeface.MONOSPACE
        val monoBold = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
        val body = paint(px(22f), mono)
        val small = paint(px(19f), mono)
        val title = paint(px(40f), Typeface.DEFAULT_BOLD)
        val footer = paint(px(24f), Typeface.DEFAULT_BOLD)
        fun lh(p: Paint) = Math.round(p.textSize * 1.3f).toFloat()
        val s = Sheet(width)

        fun dashed(before: Float = 8f, after: Float = 12f) {
            s.y += px(before)
            var x = m
            while (x < width - m) { s.rect(x, s.y, minOf(x + px(7f), width - m), s.y + px(2f)); x += px(7f) + px(5f) }
            s.y += px(2f) + px(after)
        }
        fun solid(thick: Float = 3f, before: Float = 8f, after: Float = 10f) {
            s.y += px(before)
            s.rect(m, s.y, width - m, s.y + px(thick))
            s.y += px(thick) + px(after)
        }
        fun row(left: String, right: String, p: Paint) {
            s.text(left, p, 'l', m); s.text(right, p, 'r', m); s.y += lh(p)
        }

        // Header: name big and bold, then address and website.
        s.y = px(10f)
        for (line in wrap(r.business, title, width - 2 * m)) { s.text(line, title, 'c'); s.y += lh(title) }
        if (r.business.isNotBlank()) s.y += px(4f)
        for (t in listOf(r.address, r.url)) for (line in wrap(t, small, width - 2 * m)) { s.text(line, small, 'c'); s.y += lh(small) }

        dashed(before = 12f)
        row(SimpleDateFormat("dd-MM-yyyy", Locale.US).format(r.time), SimpleDateFormat("HH:mm", Locale.US).format(r.time), small)
        row("RECEIPT", "N° ${r.number}", small)
        dashed()

        // Products: name (wrapped) on the left, amount on the right, "2 x $2.990" underneath.
        for (it in r.items) {
            val amount = Clp.format(it.amount)
            val lines = wrap(it.name, body, width - 2 * m - body.measureText(amount) - px(14f)).ifEmpty { listOf("") }
            s.text(lines[0], body, 'l', m); s.text(amount, body, 'r', m); s.y += lh(body)
            for (line in lines.drop(1)) { s.text(line, body, 'l', m); s.y += lh(body) }
            if (it.qty.compareTo(BigDecimal.ONE) != 0) {
                s.text("  ${Clp.qty(it.qty)} x ${Clp.format(it.price)}", small, 'l', m); s.y += lh(small)
            }
            s.y += px(4f)
        }

        dashed(before = 4f)
        row("Items", r.count, small)
        solid(before = 6f)

        // Total: as big as fits.
        val total = Clp.format(r.total)
        val big = paint(px(34f), monoBold)
        while (big.textSize > body.textSize && big.measureText("TOTAL  $total") > width - 2 * m) big.textSize -= 1f
        row("TOTAL", total, big)
        solid(thick = 2f, before = 2f, after = 0f)
        solid(thick = 2f, before = 3f, after = 0f)

        // Footer and barcode.
        s.y += px(18f)
        for (line in wrap(r.footer, footer, width - 2 * m)) { s.text(line, footer, 'c'); s.y += lh(footer) }
        s.y += px(14f)
        val mods = BooleanArray(10) + Code128Writer().encode(r.number) + BooleanArray(10)   // quiet zones
        val scale = width / mods.size
        require(scale > 0) { "receipt number too long for a barcode on this paper" }
        val left = ((width - mods.size * scale) / 2).toFloat()
        val barH = px(64f)
        mods.forEachIndexed { i, on -> if (on) s.rect(left + i * scale, s.y, left + (i + 1) * scale, s.y + barH) }
        s.y += barH + px(6f)
        s.text(r.number, small, 'c')
        s.y += lh(small) + px(12f)
        return s.bitmap()
    }
}

package com.ipreent

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Typeface
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import androidx.annotation.StringRes
import com.google.zxing.BarcodeFormat
import com.google.zxing.MultiFormatWriter
import com.google.zxing.EncodeHintType

enum class Dither(@StringRes val label: Int) {
    FLOYD(R.string.dither_floyd), ATKINSON(R.string.dither_atkinson), THRESHOLD(R.string.dither_threshold)
}

/** Turn images and text into rows of 0/1 pixels at the printer's width. */
object Imaging {
    /** Grayscale 0..255 per pixel, scaled to [width], landscape rotated to use the paper. */
    fun toGray(src: Bitmap, width: Int, autoRotate: Boolean = true, brightness: Float = 0f, contrast: Float = 1f): Pair<FloatArray, Int> {
        var bmp = src
        if (autoRotate && bmp.width > bmp.height * 1.3f)
            bmp = Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, Matrix().apply { postRotate(90f) }, true)
        val h = maxOf(1, Math.round(bmp.height.toFloat() * width / bmp.width))
        val scaled = Bitmap.createScaledBitmap(bmp, width, h, true)
        val px = IntArray(width * h)
        scaled.getPixels(px, 0, width, 0, 0, width, h)
        val g = FloatArray(px.size) { i ->
            val c = px[i]
            val a = Color.alpha(c) / 255f
            val l = 0.299f * Color.red(c) + 0.587f * Color.green(c) + 0.114f * Color.blue(c)
            val onWhite = l * a + 255f * (1 - a)
            ((onWhite - 128f) * contrast + 128f + brightness * 255f).coerceIn(0f, 255f)
        }
        return g to h
    }

    fun rows(gray: FloatArray, width: Int, height: Int, dither: Dither, threshold: Int = 128): List<ByteArray> {
        val g = gray.copyOf()
        val out = List(height) { ByteArray(width) }
        fun spread(x: Int, y: Int, e: Float) {
            if (x in 0 until width && y < height) g[y * width + x] += e
        }
        for (y in 0 until height) for (x in 0 until width) {
            val old = g[y * width + x]
            val black = old < threshold
            out[y][x] = if (black) 1 else 0
            val err = old - if (black) 0f else 255f
            when (dither) {
                Dither.FLOYD -> {
                    spread(x + 1, y, err * 7 / 16); spread(x - 1, y + 1, err * 3 / 16)
                    spread(x, y + 1, err * 5 / 16); spread(x + 1, y + 1, err / 16)
                }
                Dither.ATKINSON -> {
                    val e = err / 8
                    spread(x + 1, y, e); spread(x + 2, y, e); spread(x - 1, y + 1, e)
                    spread(x, y + 1, e); spread(x + 1, y + 1, e); spread(x, y + 2, e)
                }
                Dither.THRESHOLD -> {}
            }
        }
        return out
    }

    /** Rows as a black/white bitmap, for an exact preview of what will print. */
    fun preview(rows: List<ByteArray>, width: Int): Bitmap {
        val h = maxOf(1, rows.size)
        val px = IntArray(width * h) { Color.WHITE }
        rows.forEachIndexed { y, r -> for (x in 0 until width) if (r[x].toInt() != 0) px[y * width + x] = Color.BLACK }
        return Bitmap.createBitmap(px, width, h, Bitmap.Config.ARGB_8888)
    }

    fun textBitmap(text: String, width: Int, size: Float = 28f, bold: Boolean = false, margin: Int = 4): Bitmap {
        val paint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
            textSize = size; color = Color.BLACK
            typeface = if (bold) Typeface.DEFAULT_BOLD else Typeface.DEFAULT
        }
        val layout = StaticLayout.Builder.obtain(text, 0, text.length, paint, width - 2 * margin)
            .setAlignment(Layout.Alignment.ALIGN_NORMAL).build()
        val bmp = Bitmap.createBitmap(width, layout.height + 2 * margin, Bitmap.Config.ARGB_8888)
        Canvas(bmp).apply { drawColor(Color.WHITE); translate(margin.toFloat(), margin.toFloat()); layout.draw(this) }
        return bmp
    }

    /** Checklist: one empty box per line. */
    fun checklistBitmap(title: String, items: List<String>, width: Int, size: Float = 28f): Bitmap {
        val head = if (title.isNotBlank()) textBitmap(title, width, size * 1.3f, bold = true) else null
        val box = size.toInt()
        val parts = items.filter { it.isNotBlank() }.map { textBitmap(it, width - box - 16, size) }
        val h = (head?.height ?: 0) + parts.sumOf { maxOf(it.height, box + 8) + 4 }
        val bmp = Bitmap.createBitmap(width, maxOf(1, h), Bitmap.Config.ARGB_8888)
        val c = Canvas(bmp).apply { drawColor(Color.WHITE) }
        val stroke = Paint().apply { style = Paint.Style.STROKE; strokeWidth = 3f; color = Color.BLACK }
        var y = 0f
        head?.let { c.drawBitmap(it, 0f, 0f, null); y += it.height }
        for (p in parts) {
            c.drawRect(6f, y + 6, 6f + box - 4, y + box + 2, stroke)
            c.drawBitmap(p, box + 12f, y, null)
            y += maxOf(p.height, box + 8) + 4
        }
        return bmp
    }

    /** Banner: huge text running along the paper (rotated 90°). */
    fun bannerBitmap(text: String, width: Int): Bitmap {
        val paint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.BLACK; typeface = Typeface.DEFAULT_BOLD }
        paint.textSize = width * 0.85f
        val fm = paint.fontMetrics
        val len = maxOf(1, paint.measureText(text).toInt() + 20)
        val tall = (fm.descent - fm.ascent).toInt()
        val strip = Bitmap.createBitmap(len, tall, Bitmap.Config.ARGB_8888)
        Canvas(strip).apply { drawColor(Color.WHITE); drawText(text, 10f, -fm.ascent, paint) }
        return Bitmap.createBitmap(strip, 0, 0, len, tall, Matrix().apply { postRotate(90f) }, true)
    }

    fun codeBitmap(content: String, format: BarcodeFormat, width: Int): Bitmap {
        val square = format == BarcodeFormat.QR_CODE
        val w = if (square) width * 3 / 4 else width - 16
        val h = if (square) w else width / 3
        val m = MultiFormatWriter().encode(content, format, w, h, mapOf(EncodeHintType.MARGIN to 1))
        val bmp = Bitmap.createBitmap(width, m.height + 16, Bitmap.Config.ARGB_8888)
        bmp.eraseColor(Color.WHITE)
        val left = (width - m.width) / 2
        for (y in 0 until m.height) for (x in 0 until m.width) if (m[x, y]) bmp.setPixel(left + x, 8 + y, Color.BLACK)
        return bmp
    }
}

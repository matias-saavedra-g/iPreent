package com.ipreent

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Rect
import android.graphics.Typeface
import android.net.Uri
import android.text.TextPaint
import com.caverock.androidsvg.RenderOptions
import com.caverock.androidsvg.SVG
import java.io.File

/**
 * Draws [Templates]: the SVG art with AndroidSVG, the text with the bundled fonts (Fredoka, Pacifico; SIL Open
 * Font License, in assets/fonts) and Android's own fallback fonts for emoji. Python twin: templates.render.
 */
object TemplateArt {
    private var fonts: Map<String, Typeface> = emptyMap()
    private var builtin: List<Templates.Template>? = null
    private lateinit var mineDir: File

    fun init(ctx: Context) {
        if (fonts.isNotEmpty()) return
        val a = ctx.assets
        fonts = mapOf(
            "round" to runCatching { Typeface.createFromAsset(a, "fonts/Fredoka-SemiBold.ttf") }.getOrDefault(Typeface.DEFAULT_BOLD),
            "script" to runCatching { Typeface.createFromAsset(a, "fonts/Pacifico-Regular.ttf") }.getOrDefault(Typeface.DEFAULT_BOLD),
            "sans" to Typeface.DEFAULT, "bold" to Typeface.DEFAULT_BOLD,
        )
        mineDir = File(ctx.filesDir, "templates")
        builtin = (a.list("templates") ?: emptyArray()).filter { it.endsWith(".svg") }.sorted().map { name ->
            Templates.parse(a.open("templates/$name").bufferedReader().use { it.readText() }, Templates.idOf(name))
        }
    }

    /** Built-in templates, then the user's own SVGs (Mine). */
    fun all(): List<Templates.Template> = (builtin ?: emptyList()) + mine()

    private fun mine(): List<Templates.Template> =
        (mineDir.listFiles { f -> f.name.endsWith(".svg", ignoreCase = true) } ?: emptyArray()).sortedBy { it.name }.mapNotNull { f ->
            runCatching { Templates.parse(f.readText(), Templates.idOf(f.name)).copy(category = "mine") }.getOrNull()
        }

    /** Copies a picked SVG into Mine after checking it can be drawn. Returns the new template. */
    fun import(ctx: Context, uri: Uri): Templates.Template {
        val text = ctx.contentResolver.openInputStream(uri)?.use { it.readBytes() }?.toString(Charsets.UTF_8)
            ?: throw Templates.TemplateError("can't read the file")
        val name = (Sources.displayName(ctx, uri) ?: "my-template").substringBeforeLast('.')
            .replace(Regex("[^A-Za-z0-9_-]+"), "-").trim('-').ifEmpty { "my-template" }
        val t = Templates.parse(text, Templates.idOf(name)).copy(category = "mine")
        render(t, null, 64)
        mineDir.mkdirs()
        File(mineDir, "${t.id}.svg").writeText(text)      // named by id, so delete() finds it
        return t
    }

    fun delete(t: Templates.Template) {
        File(mineDir, "${t.id}.svg").delete()
    }

    private fun paint(font: String, size: Int, color: String) = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = fonts[font] ?: Typeface.DEFAULT
        textSize = size.toFloat()
        this.color = if (color == "white") Color.WHITE else Color.BLACK
    }

    /** The filled-in template [width] dots wide (print it sharp, with a threshold, not dithered). */
    fun render(t: Templates.Template, values: Map<String, String>?, width: Int): Bitmap {
        val lay = Templates.layout(t, values, width) { s, size, font -> paint(font, size, "black").measureText(s).toDouble() }
        val art = Bitmap.createBitmap(width, lay.artHeight, Bitmap.Config.ARGB_8888)
        Canvas(art).apply {
            drawColor(Color.WHITE)
            val svg = try { SVG.getFromString(t.svg) } catch (e: Exception) { throw Templates.TemplateError("can't draw this SVG (${e.message})") }
            // Without this AndroidSVG draws at the file's own width/height and ignores the viewport's size.
            if (svg.documentViewBox == null) svg.setDocumentViewBox(0f, 0f, t.width.toFloat(), t.height.toFloat())
            svg.setDocumentWidth("100%")
            svg.setDocumentHeight("100%")
            svg.renderToCanvas(this, RenderOptions.create().viewPort(0f, 0f, width.toFloat(), lay.artHeight.toFloat()))
        }
        val out = if (lay.extra <= 0) art else Bitmap.createBitmap(width, lay.height, Bitmap.Config.ARGB_8888).also {
            val at = lay.stretchAt
            Canvas(it).apply {      // repeat row `at` to make room, like templates.stretched
                drawBitmap(art, Rect(0, 0, width, at), Rect(0, 0, width, at), null)
                drawBitmap(art, Rect(0, at, width, at + 1), Rect(0, at, width, at + lay.extra), null)
                drawBitmap(art, Rect(0, at, width, lay.artHeight), Rect(0, at + lay.extra, width, lay.height), null)
            }
        }
        val c = Canvas(out)
        for (item in lay.items) when (item) {
            is Templates.Text -> c.drawText(item.text, item.x.toFloat(), item.baseline.toFloat(), paint(item.font, item.size, item.color))
            is Templates.Mark -> drawMark(c, item)
        }
        return out
    }

    private fun drawMark(c: Canvas, m: Templates.Mark) {
        val ink = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = if (m.color == "white") Color.WHITE else Color.BLACK }
        val r = (m.size / 2).toFloat()
        val cx = m.cx.toFloat(); val cy = m.cy.toFloat()
        when (m.kind) {
            "check" -> {
                ink.style = Paint.Style.STROKE
                ink.strokeWidth = maxOf(2, Math.floor(m.size / 9 + 0.5).toInt()).toFloat()
                c.drawRect(cx - r, cy - r, cx + r, cy + r, ink)
            }
            "dot" -> c.drawCircle(cx, cy, (m.size * 0.22).toFloat(), ink)
            "heart" -> {
                val pts = Templates.heartPoints(m.cx, m.cy, m.size * 0.85)
                val p = Path()
                pts.forEachIndexed { i, (x, y) -> if (i == 0) p.moveTo(x.toFloat(), y.toFloat()) else p.lineTo(x.toFloat(), y.toFloat()) }
                p.close()
                c.drawPath(p, ink)
            }
        }
    }
}

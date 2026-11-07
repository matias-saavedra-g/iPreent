package com.ipreent

import org.w3c.dom.Element
import java.io.StringReader
import javax.xml.XMLConstants
import javax.xml.parsers.DocumentBuilderFactory
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import org.xml.sax.InputSource

/**
 * Templates: cute SVG designs with text boxes you fill in. Port of ipreent/templates.py: the same SVG files
 * (assets/templates, kept identical to ipreent/templates by a Python test), the same layout rules and the
 * same test cases (TemplatesTest.kt ↔ tests/test_templates.py). Drawing lives in [TemplateArt] (Android only),
 * so this file runs in plain JVM unit tests.
 *
 * Format (docs/TEMPLATES.md): an ordinary SVG; attributes in the `urn:ipreent:template` namespace name it
 * (`ip:name`, `ip:category`), mark invisible rectangles as text boxes (`ip:field`, `ip:label`, `ip:default`,
 * `ip:font`, `ip:size`, `ip:min`, `ip:align`, `ip:valign`, `ip:list`, `ip:lines`, `ip:color`) and let the design
 * grow taller at one row (`ip:stretch`) when a box crossing it needs more room than its smallest font gives.
 */
object Templates {
    const val NS = "urn:ipreent:template"
    private const val SVG_NS = "http://www.w3.org/2000/svg"
    val CATEGORIES = linkedMapOf("love" to "Love", "frames" to "Frames", "lists" to "Lists", "notes" to "Notes",
        "party" to "Party", "labels" to "Labels", "christmas" to "Christmas", "holidays" to "Holidays", "mine" to "Mine")
    val FONTS = listOf("round", "script", "sans", "bold")
    val LISTS = listOf("none", "check", "dot", "heart")
    const val LINE_HEIGHT = 1.25
    const val CAP = 0.7
    const val MIN_PX = 8

    class TemplateError(message: String) : Exception(message)

    data class Field(
        val key: String, val label: String, val default: String,
        val x: Double, val y: Double, val w: Double, val h: Double,
        val font: String = "round", val size: Double = 32.0, val min: Double = 14.0,
        val align: String = "center", val valign: String = "middle", val list: String = "none",
        val lines: Int = 0, val color: String = "black",
    ) {
        val multiline get() = lines != 1
    }

    data class Template(
        val id: String, val name: String, val category: String,
        val width: Double, val height: Double, val stretch: Double?, val fields: List<Field>,
        val svg: String, val season: Season? = null,
    ) {
        fun defaults() = fields.associate { it.key to it.default }
        /** True if [month]/[day] falls in the template's `ip:season`. */
        fun inSeason(month: Int, day: Int) = season?.contains(month, day) ?: false
    }

    /** `ip:season="11-01..12-26"`: inclusive, and it may wrap past New Year (`12-15..01-06`). */
    data class Season(val startMonth: Int, val startDay: Int, val endMonth: Int, val endDay: Int) {
        fun contains(month: Int, day: Int): Boolean {
            val d = month * 100 + day; val a = startMonth * 100 + startDay; val b = endMonth * 100 + endDay
            return if (a <= b) d in a..b else d >= a || d <= b
        }
    }

    private val SEASON = Regex("""\s*(\d{1,2})-(\d{1,2})\s*\.\.\s*(\d{1,2})-(\d{1,2})\s*""")
    fun season(v: String?): Season? {
        val (a, b, c, d) = SEASON.matchEntire(v ?: return null)?.destructured?.toList()?.map { it.toInt() } ?: return null
        if (a !in 1..12 || c !in 1..12 || b !in 1..31 || d !in 1..31) return null
        return Season(a, b, c, d)
    }

    /** Templates in season first, the rest in file order (same as templates.gallery_order). */
    fun galleryOrder(items: List<Template>, month: Int, day: Int) = items.sortedBy { !it.inSeason(month, day) }

    /** Category keys for the chips: those with a template in season first, then [CATEGORIES] order; only used ones. */
    fun categoryOrder(items: List<Template>, month: Int, day: Int): List<String> {
        val hot = items.filter { it.inSeason(month, day) }.map { it.category }.toSet()
        return CATEGORIES.keys.filter { k -> items.any { it.category == k } }.sortedBy { it !in hot }
    }

    private fun halfUp(v: Double) = floor(v + 0.5).toInt()

    private val NUMBER = Regex("""^\s*([-+]?[\d.]+(?:[eE][-+]?\d+)?)""")
    private fun num(v: String?, default: Double = 0.0) =
        v?.let { NUMBER.find(it)?.groupValues?.get(1)?.toDoubleOrNull() } ?: default

    private fun Element.ip(name: String): String? = if (hasAttributeNS(NS, name)) getAttributeNS(NS, name) else null
    private fun Element.attr(name: String): String? = if (hasAttribute(name)) getAttribute(name) else null

    /** `10-big-heart.svg` → `big-heart` (the number only orders the gallery). */
    fun idOf(fileName: String) = fileName.substringAfterLast('/').substringBeforeLast('.').replace(Regex("^\\d+-"), "")

    fun parse(svg: String, id: String = "template"): Template {
        val f = DocumentBuilderFactory.newInstance().apply { isNamespaceAware = true }
        runCatching { f.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true) }
        runCatching { f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true) }
        val root = try {
            f.newDocumentBuilder().parse(InputSource(StringReader(svg))).documentElement
        } catch (e: Exception) {
            throw TemplateError("not a valid SVG file (${e.message})")
        }
        if (root.localName != "svg" || (root.namespaceURI != null && root.namespaceURI != SVG_NS)) throw TemplateError("not an SVG file")
        val vb = (root.attr("viewBox") ?: "").replace(",", " ").trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
        val ox: Double; val oy: Double; val w: Double; val h: Double
        if (vb.size == 4 && num(vb[2]) > 0 && num(vb[3]) > 0) {
            ox = num(vb[0]); oy = num(vb[1]); w = num(vb[2]); h = num(vb[3])
        } else {
            ox = 0.0; oy = 0.0; w = num(root.attr("width"), 384.0); h = num(root.attr("height"), 384.0)
            if (w <= 0 || h <= 0) throw TemplateError("the SVG has no size (viewBox or width/height)")
        }
        val stretch = root.ip("stretch")?.let { num(it) - oy }?.takeIf { it > 0 && it < h }
        val fields = mutableListOf<Field>()
        val seen = mutableSetOf<String>()
        val all = root.getElementsByTagName("*")
        for (i in -1 until all.length) {
            val el = if (i < 0) root else all.item(i) as Element
            val key = el.ip("field")
            if (key.isNullOrEmpty() || !seen.add(key)) continue
            val size = num(el.ip("size"), 32.0)
            val font = el.ip("font") ?: "round"
            val mark = el.ip("list") ?: "none"
            fields += Field(
                key = key, label = el.ip("label") ?: key.replaceFirstChar { it.uppercase() }, default = el.ip("default") ?: "",
                x = num(el.attr("x")) - ox, y = num(el.attr("y")) - oy, w = num(el.attr("width")), h = num(el.attr("height")),
                font = if (font in FONTS) font else "round", size = size, min = min(size, num(el.ip("min"), 14.0)),
                align = el.ip("align")?.takeIf { it == "left" || it == "right" } ?: "center",
                valign = if (el.ip("valign") == "top") "top" else "middle",
                list = if (mark in LISTS) mark else "none", lines = num(el.ip("lines"), 0.0).toInt(),
                color = if (el.ip("color") == "white") "white" else "black",
            )
        }
        val category = root.ip("category") ?: "mine"
        return Template(id, root.ip("name")?.takeIf { it.isNotEmpty() } ?: id.replace("-", " ").replaceFirstChar { it.uppercase() },
            if (category in CATEGORIES) category else "mine", w, h, stretch, fields.filter { it.w > 0 && it.h > 0 }, svg,
            season(root.ip("season")))
    }

    // ---- layout: the same rules (and test cases) as templates.py ----

    data class Line(val text: String, val first: Boolean)

    /** Greedy word wrap; list items (one per typed line) skip blank lines; too-long words split between characters. */
    fun wrap(text: String, width: Double, measure: (String) -> Double, indent: Double = 0.0, items: Boolean = false): List<Line> {
        val out = mutableListOf<Line>()
        val avail = max(1.0, width - indent)
        for (para in text.split("\n")) {
            val words = para.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
            if (words.isEmpty()) { if (!items) out += Line("", true); continue }
            var first = true
            var cur = ""
            for (word in words) {
                val trial = if (cur.isEmpty()) word else "$cur $word"
                if (measure(trial) <= avail) { cur = trial; continue }
                if (cur.isNotEmpty()) { out += Line(cur, first); first = false }
                cur = ""
                var i = 0
                while (i < word.length) {                     // a word wider than the line: split it
                    val ch = String(Character.toChars(word.codePointAt(i)))
                    if (cur.isNotEmpty() && measure(cur + ch) > avail) { out += Line(cur, first); first = false; cur = "" }
                    cur += ch
                    i += ch.length
                }
            }
            out += Line(cur, first)
        }
        if (!items) while (out.isNotEmpty() && out.last().text.isEmpty()) out.removeAt(out.size - 1)
        return out
    }

    data class Fit(val size: Int, val lines: List<Line>, val height: Double, val fits: Boolean)

    fun indent(mark: String, size: Int) = if (mark == "none") 0.0 else halfUp(size * 1.1).toDouble()

    /** Largest whole font size from [size] down to [minimum] at which [text] fits in w×h. */
    fun fit(text: String, w: Double, h: Double, size: Int, minimum: Int, measure: (String, Int) -> Double,
            mark: String = "none", lines: Int = 0): Fit {
        val top = max(MIN_PX, size)
        val low = max(MIN_PX, min(minimum, size))
        var s = top
        while (true) {
            val got = wrap(text, w, { measure(it, s) }, indent(mark, s), mark != "none")
            val need = got.size * s * LINE_HEIGHT
            val ok = need <= h + 0.5 && (lines <= 0 || got.size <= lines)
            if (ok || s <= low) return Fit(s, got, need, ok)
            s--
        }
    }

    sealed interface Item
    data class Text(val text: String, val x: Double, val baseline: Double, val size: Int, val font: String, val color: String) : Item
    data class Mark(val kind: String, val cx: Double, val cy: Double, val size: Double, val color: String) : Item
    data class Layout(val width: Int, val height: Int, val artHeight: Int, val stretchAt: Int, val extra: Int, val items: List<Item>)

    private class Placed(val f: Field, val fit: Fit, val x: Double, var y: Double, val w: Double, var h: Double)

    /** Where every line goes at [width] dots. values: key → text (missing = example text). measure(text, size, font). */
    fun layout(t: Template, values: Map<String, String>?, width: Int, measure: (String, Int, String) -> Double): Layout {
        val scale = width / t.width
        val artH = max(1, halfUp(t.height * scale))
        val sy = t.stretch?.let { halfUp(it * scale) }
        val placed = t.fields.map { f ->
            val text = values?.get(f.key) ?: f.default
            val x = f.x * scale; val y = f.y * scale; val w = f.w * scale; val h = f.h * scale
            Placed(f, fit(text, w, h, halfUp(f.size * scale), halfUp(f.min * scale), { s, size -> measure(s, size, f.font) }, f.list, f.lines), x, y, w, h)
        }
        var extra = 0
        if (sy != null) {
            for (p in placed)
                if (!p.fit.fits && p.y < sy && sy < p.y + p.h && (p.f.lines <= 0 || p.fit.lines.size <= p.f.lines))
                    extra = max(extra, ceil(p.fit.height - p.h).toInt())
            for (p in placed) {
                if (p.y < sy && sy < p.y + p.h) p.h += extra
                else if (p.y >= sy) p.y += extra
            }
        }
        val items = mutableListOf<Item>()
        for (p in placed) {
            if (p.fit.lines.none { it.text.isNotEmpty() }) continue
            val f = p.f
            val s = p.fit.size
            val lh = s * LINE_HEIGHT
            val lines = if (f.lines > 0) p.fit.lines.take(f.lines) else p.fit.lines
            val top = if (f.valign == "top") p.y else p.y + (p.h - lines.size * lh) / 2
            val ind = indent(f.list, s)
            lines.forEachIndexed { i, line ->
                val base = top + i * lh + (lh + CAP * s) / 2
                val lx = when {
                    f.list != "none" -> {
                        if (line.first) items += Mark(f.list, p.x + ind * 0.4, base - CAP * s / 2, CAP * s, f.color)
                        p.x + ind
                    }
                    f.align == "left" -> p.x
                    else -> {
                        val lw = measure(line.text, s, f.font)
                        if (f.align == "center") p.x + (p.w - lw) / 2 else p.x + p.w - lw
                    }
                }
                if (line.text.isNotEmpty()) items += Text(line.text, lx, base, s, f.font, f.color)
            }
        }
        return Layout(width, artH + extra, artH, if (extra > 0) sy!! else 0, extra, items)
    }

    /** A heart [size] tall centred on (cx, cy): the classic parametric curve, as in templates.heart_points. */
    fun heartPoints(cx: Double, cy: Double, size: Double, n: Int = 40): List<Pair<Double, Double>> = (0 until n).map { i ->
        val a = 2 * Math.PI * i / n
        val x = 16 * Math.pow(Math.sin(a), 3.0)
        val y = 13 * Math.cos(a) - 5 * Math.cos(2 * a) - 2 * Math.cos(3 * a) - Math.cos(4 * a)
        (cx + x * size / 32) to (cy - (y + 2.5) * size / 30)
    }
}

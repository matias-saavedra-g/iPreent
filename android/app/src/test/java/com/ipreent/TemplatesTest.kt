package com.ipreent

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** Same cases as tests/test_templates.py (the shared part). */
class TemplatesTest {
    private fun mono(s: String, size: Int = 10) = s.length * size * 0.5

    private val sample = """<svg xmlns="http://www.w3.org/2000/svg" xmlns:ip="urn:ipreent:template" viewBox="0 0 200 100"
     ip:name="Sample" ip:category="notes" ip:stretch="50">
  <rect x="0" y="0" width="200" height="100" fill="none" stroke="#000"/>
  <rect ip:field="title" ip:default="Hi" ip:size="20" ip:min="10" ip:lines="1" x="10" y="5" width="180" height="30" fill="none"/>
  <rect ip:field="items" ip:label="Items" ip:default="a&#10;b" ip:list="check" ip:size="10" ip:min="10"
        ip:valign="top" x="10" y="40" width="180" height="30" fill="none"/>
  <rect ip:field="foot" ip:default="end" ip:size="10" ip:align="right" x="10" y="80" width="180" height="15" fill="none"/>
</svg>"""

    private val measure = { s: String, size: Int, _: String -> s.length * size * 0.5 }

    @Test fun wrapWordsAndLongWords() {
        assertEquals(listOf("the quick", "brown fox"), Templates.wrap("the quick brown fox", 50.0, { mono(it) }).map { it.text })
        val lines = Templates.wrap("abcdefghijklmnop", 50.0, { mono(it) })
        assertEquals(listOf("abcdefghij", "klmnop"), lines.map { it.text })
        assertEquals(listOf(true, false), lines.map { it.first })
    }

    @Test fun wrapKeepsBlankLinesExceptInLists() {
        assertEquals(listOf("a", "", "b"), Templates.wrap("a\n\nb\n", 50.0, { mono(it) }).map { it.text })
        val lines = Templates.wrap("one two three\n\nfour", 40.0, { mono(it) }, indent = 10.0, items = true)
        assertEquals(listOf("one" to true, "two" to false, "three" to false, "four" to true), lines.map { it.text to it.first })
    }

    @Test fun fitShrinksUntilItFits() {
        val m = { s: String, size: Int -> s.length * size * 0.5 }
        val f = Templates.fit("hello world", 100.0, 40.0, 30, 10, m)
        assertEquals(18, f.size); assertEquals(listOf("hello world"), f.lines.map { it.text }); assertTrue(f.fits)
        val g = Templates.fit("hello world", 100.0, 10.0, 30, 12, m)
        assertEquals(12, g.size); assertFalse(g.fits); assertEquals(15.0, g.height, 1e-9)
        assertEquals(30, Templates.fit("a b c", 100.0, 100.0, 30, 10, m, lines = 1).size)
    }

    @Test fun parseReadsFieldsAndStretch() {
        val t = Templates.parse(sample, "sample")
        assertEquals(listOf("Sample", "notes"), listOf(t.name, t.category))
        assertEquals(listOf(200.0, 100.0, 50.0), listOf(t.width, t.height, t.stretch))
        val (title, items, foot) = t.fields
        assertEquals(listOf("title", "Title"), listOf(title.key, title.label)); assertEquals(1, title.lines); assertFalse(title.multiline)
        assertEquals(listOf("a\nb", "check", "top"), listOf(items.default, items.list, items.valign))
        assertEquals(listOf("right", "round"), listOf(foot.align, foot.font)); assertEquals(10.0, foot.min, 0.0)
        assertEquals(mapOf("title" to "Hi", "items" to "a\nb", "foot" to "end"), t.defaults())
    }

    @Test fun layoutPositionsAndStretch() {
        val t = Templates.parse(sample, "sample")
        val lay = Templates.layout(t, mapOf("items" to "a\nb\nc\nd"), 400, measure)
        assertEquals(listOf(240, 200, 100, 40), listOf(lay.height, lay.artHeight, lay.stretchAt, lay.extra))
        val texts = lay.items.filterIsInstance<Templates.Text>()
        val marks = lay.items.filterIsInstance<Templates.Mark>()
        assertEquals(listOf("Hi", "a", "b", "c", "d", "end"), texts.map { it.text })
        val hi = texts.first(); val a = texts[1]; val end = texts.last()
        assertEquals(40, hi.size); assertEquals(180.0, hi.x, 1e-9); assertEquals(54.0, hi.baseline, 1e-9)
        assertEquals(20, a.size); assertEquals(42.0, a.x, 1e-9); assertEquals(99.5, a.baseline, 1e-9)
        assertEquals(4, marks.size); assertEquals(28.8, marks[0].cx, 1e-9); assertEquals(92.5, marks[0].cy, 1e-9)
        assertEquals(350.0, end.x, 1e-9); assertEquals(222.0, end.baseline, 1e-9)
        assertEquals(0, Templates.layout(t, null, 400, measure).extra)
    }

    @Test fun emptyFieldsDrawNothing() {
        val t = Templates.parse(sample, "sample")
        val lay = Templates.layout(t, mapOf("title" to "", "items" to "", "foot" to " "), 200, measure)
        assertTrue(lay.items.isEmpty()); assertEquals(100, lay.height)
    }

    // Same cases as test_seasons_and_gallery_order in tests/test_templates.py
    @Test fun seasonsAndGalleryOrder() {
        assertEquals(Templates.Season(11, 1, 12, 26), Templates.season("11-01..12-26"))
        assertEquals(Templates.Season(12, 15, 1, 6), Templates.season(" 12-15 .. 01-06 "))
        assertEquals(null, Templates.season("13-01..12-26"))
        assertEquals(null, Templates.season("Christmas"))
        assertEquals(null, Templates.season(null))
        val head = "<svg xmlns=\"http://www.w3.org/2000/svg\" xmlns:ip=\"urn:ipreent:template\" viewBox=\"0 0 384 100\" "
        val box = "><rect ip:field=\"a\" x=\"0\" y=\"0\" width=\"10\" height=\"10\"/></svg>"
        val xmas = Templates.parse(head + "ip:category=\"christmas\" ip:season=\"11-01..12-26\"" + box, "xmas")
        val ny = Templates.parse(head + "ip:category=\"holidays\" ip:season=\"12-15..01-06\"" + box, "ny")
        val love = Templates.parse(head + "ip:category=\"love\"" + box, "love")
        assertTrue(xmas.inSeason(11, 1) && xmas.inSeason(12, 26) && !xmas.inSeason(12, 27) && !xmas.inSeason(10, 31))
        assertTrue(ny.inSeason(12, 31) && ny.inSeason(1, 6) && !ny.inSeason(1, 7) && !ny.inSeason(12, 14))
        assertTrue(!love.inSeason(2, 14))
        val items = listOf(love, ny, xmas)
        assertEquals(listOf("xmas", "love", "ny"), Templates.galleryOrder(items, 11, 7).map { it.id })
        assertEquals(listOf("ny", "xmas", "love"), Templates.galleryOrder(items, 12, 20).map { it.id })
        assertEquals(listOf("love", "ny", "xmas"), Templates.galleryOrder(items, 7, 1).map { it.id })
        assertEquals(listOf("christmas", "love", "holidays"), Templates.categoryOrder(items, 11, 7))
        assertEquals(listOf("holidays", "love", "christmas"), Templates.categoryOrder(items, 1, 2))
        assertEquals(listOf("love", "christmas", "holidays"), Templates.categoryOrder(items, 7, 1))
    }

    @Test fun bundledTemplatesParse() {
        val files = File("src/main/assets/templates").listFiles { f -> f.name.endsWith(".svg") }!!.sortedBy { it.name }
        assertTrue(files.size >= 15)
        val all = files.map { Templates.parse(it.readText(), Templates.idOf(it.name)) }
        assertEquals(all.size, all.map { it.id }.toSet().size)
        for (t in all) {
            assertEquals(t.id, 384.0, t.width, 0.0)
            assertTrue(t.id, t.fields.isNotEmpty() && t.category != "mine")
            if (t.category == "christmas" || t.category == "holidays") assertTrue(t.id, t.season != null)
        }
        assertTrue(all.count { it.category == "christmas" } >= 6)
        assertEquals("big-heart", Templates.idOf("10-big-heart.svg"))
    }

    @Test(expected = Templates.TemplateError::class) fun badFilesRaise() { Templates.parse("<html/>") }
}

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

    @Test fun bundledTemplatesParse() {
        val files = File("src/main/assets/templates").listFiles { f -> f.name.endsWith(".svg") }!!.sortedBy { it.name }
        assertTrue(files.size >= 15)
        val all = files.map { Templates.parse(it.readText(), Templates.idOf(it.name)) }
        assertEquals(all.size, all.map { it.id }.toSet().size)
        for (t in all) {
            assertEquals(t.id, 384.0, t.width, 0.0)
            assertTrue(t.id, t.fields.isNotEmpty() && t.category != "mine")
        }
        assertEquals("big-heart", Templates.idOf("10-big-heart.svg"))
    }

    @Test(expected = Templates.TemplateError::class) fun badFilesRaise() { Templates.parse("<html/>") }
}

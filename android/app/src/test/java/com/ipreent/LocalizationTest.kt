package com.ipreent

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.w3c.dom.Element
import java.io.File
import javax.xml.parsers.DocumentBuilderFactory

/** The Spanish translation says the same things as the English (no Python twin: the Windows app is English only). */
class LocalizationTest {
    private val ARG = Regex("%(\\d+\\$)?[sd]")

    /** name → text of every translatable string, and name → text of every plural item (by quantity). */
    private fun read(path: String): Pair<Map<String, String>, Map<String, List<String>>> {
        val doc = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(File(path))
        val strings = linkedMapOf<String, String>(); val plurals = linkedMapOf<String, List<String>>()
        val nodes = doc.documentElement.childNodes
        for (i in 0 until nodes.length) {
            val e = nodes.item(i) as? Element ?: continue
            when (e.tagName) {
                "string" -> if (e.getAttribute("translatable") != "false") strings[e.getAttribute("name")] = e.textContent
                "plurals" -> plurals[e.getAttribute("name")] =
                    (0 until e.getElementsByTagName("item").length).map { e.getElementsByTagName("item").item(it).textContent }
            }
        }
        return strings to plurals
    }

    private fun args(s: String) = ARG.findAll(s).map { it.value.replace(Regex("^%\\d+\\$"), "%") }.sorted().toList()

    /** A string missing in Spanish is fine (Android falls back to English); one that exists must say the same thing. */
    @Test fun spanishStringsAreKnownAndHaveTheSameArguments() {
        val (en, enPlurals) = read("src/main/res/values/strings.xml")
        val (es, esPlurals) = read("src/main/res/values-es/strings.xml")
        assertTrue("strings only in values-es: ${es.keys - en.keys}", en.keys.containsAll(es.keys))
        assertTrue("plurals only in values-es: ${esPlurals.keys - enPlurals.keys}", enPlurals.keys.containsAll(esPlurals.keys))
        for ((name, text) in es) assertEquals(name, args(en.getValue(name)), args(text))
        for ((name, items) in esPlurals) for (item in items) assertEquals(name, args(enPlurals.getValue(name)[0]), args(item))
        for ((name, text) in es) assertTrue("$name is empty", text.isNotBlank())
    }

    /** Templates or boxes missing from the JSON keep their English text; the JSON must not name unknown ones. */
    @Test fun spanishTemplatesNameOnlyRealTemplatesAndBoxes() {
        val tr = JSONObject(File("src/main/assets/i18n/templates.es.json").readText())
        val files = File("src/main/assets/templates").listFiles { f -> f.name.endsWith(".svg") }!!
        val all = files.map { Templates.parse(it.readText(), Templates.idOf(it.name)) }
        assertTrue(all.map { it.id }.containsAll(tr.keys().asSequence().toList()))
        for (t in all) {
            val fields = tr.optJSONObject(t.id)?.optJSONObject("fields") ?: continue
            assertTrue(t.id, t.fields.map { it.key }.containsAll(fields.keys().asSequence().toList()))
        }
    }

    @Test fun localizeReplacesTextsAndKeepsTheLayout() {
        val svg = """<svg xmlns="http://www.w3.org/2000/svg" xmlns:ip="urn:ipreent:template" viewBox="0 0 200 100" ip:name="Cloud">
          <rect ip:field="a" ip:label="Message" ip:default="Hi" ip:size="20" x="0" y="0" width="100" height="50" fill="none"/>
          <rect ip:field="b" ip:label="Other" ip:default="Bye" x="0" y="50" width="100" height="50" fill="none"/></svg>"""
        val t = Templates.parse(svg, "cloud")
        assertEquals(t, Templates.localize(t, null))
        val l = Templates.localize(t, Templates.Translation("Nube", mapOf("a" to ("Mensaje" to "Hola"), "b" to (null to null))))
        assertEquals(listOf("Nube", "Mensaje", "Hola"), listOf(l.name, l.fields[0].label, l.fields[0].default))
        assertEquals(listOf("Other", "Bye"), listOf(l.fields[1].label, l.fields[1].default))
        assertEquals(t.fields.map { it.size to it.h }, l.fields.map { it.size to it.h })
    }

    @Test fun userErrorsKeepTheirEnglishMessage() {
        val e = try { Receipt.fromRows("", "", "", "", listOf(Triple("Tea", "1", ""))); null } catch (e: UserError) { e }!!
        assertEquals("Row 1: no price", e.message)
        assertEquals(R.string.err_row, e.res)
        assertEquals(listOf<Any>(1), e.args.take(1))
    }

    @Test fun stateWordsCanBeTranslated() {
        assertEquals("out of paper, low battery", Protocol.describeState(byteArrayOf(0b1001)))
        val es = mapOf("out of paper" to "sin papel", "low battery" to "batería baja", "ready" to "lista")
        assertEquals("sin papel, batería baja", Protocol.describeState(byteArrayOf(0b1001)) { es.getValue(it) })
        assertEquals("lista", Protocol.describeState(byteArrayOf(0)) { es.getValue(it) })
    }
}

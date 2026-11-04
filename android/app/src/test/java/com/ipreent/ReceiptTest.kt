package com.ipreent

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import java.math.BigDecimal

/** Same cases as tests/test_receipt.py, so both apps total and format money alike. */
class ReceiptTest {
    @Test fun parsesChileanPrices() {
        assertEquals(12990L, Clp.parsePrice("$12.990"))
        assertEquals(12990L, Clp.parsePrice("12990"))
        assertEquals(12990L, Clp.parsePrice("12,990"))
        assertEquals(1234567L, Clp.parsePrice("1.234.567"))
        assertEquals(-1000L, Clp.parsePrice("-1.000"))
        assertEquals(-500L, Clp.parsePrice("$ -500"))
        assertEquals(12991L, Clp.parsePrice("12990.50"))
        assertThrows(IllegalArgumentException::class.java) { Clp.parsePrice("abc") }
    }

    @Test fun quantities() {
        assertEquals(BigDecimal("1.5"), Clp.parseQty("1,5"))
        assertEquals(BigDecimal.ONE, Clp.parseQty(""))
        assertEquals(BigDecimal("3"), Clp.parseQty("x3"))
        assertEquals("1,5", Clp.qty(BigDecimal("1.50")))
        assertEquals("2", Clp.qty(BigDecimal("2.0")))
        assertThrows(IllegalArgumentException::class.java) { Clp.parseQty("0") }
    }

    @Test fun formatsPesos() {
        assertEquals("$12.990", Clp.format(12990))
        assertEquals("-$1.000", Clp.format(-1000))
        assertEquals("$0", Clp.format(0))
        assertEquals("$1.234.567", Clp.format(1234567))
    }

    @Test fun totals() {
        val r = Receipt.fromRows("MT", "", "", DEFAULT_FOOTER, listOf(
            Triple("Empanada", "2", "2.990"), Triple("Queso", "0,35", "12.990"),
            Triple("", "1", ""), Triple("Descuento", "1", "-2.000")))
        assertEquals(5980L + 4547L - 2000L, r.total)
        assertEquals("3", r.count)
        assertEquals(12, r.number.length)
        val e = assertThrows(IllegalArgumentException::class.java) {
            Receipt.fromRows("", "", "", "", listOf(Triple("Pan", "1", "")))
        }
        assertEquals("Row 1: no price", e.message)
    }
}

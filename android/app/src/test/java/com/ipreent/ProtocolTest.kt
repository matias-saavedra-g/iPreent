package com.ipreent

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

/** Same vectors as tests/test_protocol.py (byte arrays hard-coded in the vendor app). */
class ProtocolTest {
    private fun b(vararg v: Int) = ByteArray(v.size) { v[it].toByte() }

    @Test fun framesMatchVendorConstants() {
        assertArrayEquals(b(81, 120, -92, 0, 1, 0, 51, -103, -1), Protocol.frame(0xA4, b(0x33)))
        assertArrayEquals(b(81, 120, -95, 0, 2, 0, 48, 0, -7, -1), Protocol.frame(0xA1, Protocol.u16(48)))
        assertArrayEquals(b(81, 120, -95, 0, 2, 0, 72, 0, -13, -1), Protocol.frame(0xA1, Protocol.u16(72)))
        assertArrayEquals(b(81, 120, -66, 0, 1, 0, 1, 7, -1), Protocol.frame(0xBE, b(1)))
        assertArrayEquals(b(81, 120, -90, 0, 11, 0, -86, 85, 23, 0, 0, 0, 0, 0, 0, 0, 23, 17, -1), Protocol.frame(0xA6, Protocol.LATTICE_END))
        assertArrayEquals(b(18, 81, 120, -88, 0, 1, 0, 0, 0, -1), Protocol.frame(0xA8, b(0), newFormat = true))
    }

    @Test fun rowEncodings() {
        val row = ByteArray(384).also { it[0] = 1 }
        assertEquals(1, Protocol.packRow(row)[0].toInt())
        assertArrayEquals(b(127, 127, 127, 3), Protocol.rleRow(ByteArray(384)))
        assertArrayEquals(b(0x83, 0x05), Protocol.rleRow(b(1, 1, 1, 0, 0, 0, 0, 0)))
        assertEquals(0xBF.toByte(), Protocol.lineFrame(ByteArray(384), true)[2])
        assertEquals(0xA2.toByte(), Protocol.lineFrame(ByteArray(384), false)[2])
    }

    @Test fun notificationParse() {
        val data = Protocol.frame(0xA3, b(1)) + Protocol.frame(0xAE, b(0x10))
        val got = Protocol.parseNotification(data)
        assertEquals(listOf(0xA3, 0xAE), got.map { it.first })
        assertArrayEquals(b(0x10), got[1].second)
        assertEquals("out of paper", Protocol.describeState(b(1)))
    }

    @Test fun sc03hProfile() {
        val table = org.json.JSONArray(java.io.File("src/main/assets/models.json").readText())
        val m = Model.lookup(table, "SC03h-5363")
        assertEquals(listOf("SC03h", "384", "true", "180"), listOf(m.name, "${m.width}", "${m.rle}", "${m.mtu}"))
    }

    // Same cases as tests/test_protocol.py
    @Test fun printTimeEstimate() {
        assertEquals(8.199, Protocol.estimateSeconds(400, 200), 1e-3)
        assertEquals(10.399, Protocol.estimateSeconds(400, 200, copies = 2, connect = false), 1e-3)
        assertEquals(4.610, Protocol.estimateSeconds(0, 200, mmPerS = 20.0), 1e-3)
        assertEquals(Protocol.estimateSeconds(400, 200), Protocol.estimateSeconds(400, 200, copies = 0), 1e-9)
    }

    @Test fun speedForEnergy() {
        assertEquals(15.0, Protocol.speedFor(5000), 1e-9)
        assertEquals(15.0, Protocol.speedFor(0), 1e-9)
        assertEquals(9.375, Protocol.speedFor(8000), 1e-3)
        assertEquals(4.412, Protocol.speedFor(17000), 1e-3)
        assertEquals(Protocol.MIN_MM_PER_S, Protocol.speedFor(500000), 1e-9)
        val learnt = mapOf(8000 to 12.0, 12000 to 10.0)
        assertEquals(12.0, Protocol.speedFor(8000, learnt), 1e-9)
        assertEquals(19.2, Protocol.speedFor(5000, learnt), 1e-3)
        assertEquals(7.059, Protocol.speedFor(17000, learnt), 1e-3)
        assertEquals(10.909, Protocol.speedFor(10000, learnt), 1e-3)
        assertEquals(11.2, Protocol.speedFor(9000, mapOf(5000 to 14.0, 17000 to 8.0)), 1e-3)
    }

    @Test fun learnSpeed() {
        assertEquals(21.539, Protocol.measuredSpeed(1600, 200, 1, 11.0)!!, 1e-3)
        assertEquals(34.462, Protocol.learnSpeed(40.0, 1600, 200, 1, 11.0), 1e-3)
        assertEquals(40.0, Protocol.learnSpeed(40.0, 10, 200, 1, 9.0), 1e-9)
        assertEquals(40.0, Protocol.learnSpeed(40.0, 1600, 200, 1, 0.5), 1e-9)
        assertEquals(40.0 + 0.3 * (2.0 - 40.0), Protocol.learnSpeed(40.0, 1600, 200, 1, 1000.0), 1e-9)
    }

    @Test fun learnSpeedsPerEnergy() {
        val one = Protocol.learnSpeeds(emptyMap(), 8000, 1600, 200, 1, 11.0)
        assertEquals(setOf(8000), one.keys)
        assertEquals(21.539, one.getValue(8000), 1e-3)
        val two = Protocol.learnSpeeds(one, 8000, 1600, 200, 1, 21.0)
        assertEquals(21.539 + 0.3 * (10.770 - 21.539), two.getValue(8000), 1e-3)
        assertEquals(one, Protocol.learnSpeeds(one, 8000, 10, 200, 1, 9.0))
        assertEquals(setOf(8000, 17000), Protocol.learnSpeeds(one, 17000, 1600, 200, 1, 31.0).keys)
        assertEquals(setOf(Protocol.REF_ENERGY), Protocol.learnSpeeds(emptyMap(), 0, 1600, 200, 1, 11.0).keys)
    }

    @Test fun formatEta() {
        assertEquals(listOf("0:00", "0:01", "0:07", "1:00", "1:30", "12:05"),
            listOf(0.0, 0.2, 7.0, 59.5, 90.0, 725.0).map { Protocol.formatEta(it) })
    }
}

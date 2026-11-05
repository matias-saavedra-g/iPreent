package com.ipreent

import org.junit.Assert.assertEquals
import org.junit.Test

/** Same cases as tests/test_features.py. */
class FeaturesTest {
    private val w = linkedMapOf("photo" to 0.24, "document" to 0.20, "text" to 0.18, "receipt" to 0.14, "banner" to 0.06)

    @Test fun priorOrderWithoutUsage() {
        assertEquals(listOf("photo", "document", "text", "receipt", "banner"), Features.ranked(w))
    }

    @Test fun usageDecaysAndAddsUp() {
        var u = Features.recordUse(emptyMap(), "receipt")
        u = Features.recordUse(u, "receipt")
        u = Features.recordUse(u, "text")
        assertEquals(1.71, u["receipt"]!!, 1e-9)
        assertEquals(1.0, u["text"]!!, 1e-9)
    }

    @Test fun habitOvertakesTheGuess() {
        var u = emptyMap<String, Double>()
        repeat(2) { u = Features.recordUse(u, "receipt") }
        assertEquals(listOf("receipt", "photo"), Features.ranked(w, u).take(2))
        assertEquals(listOf("photo", "document", "text", "banner", "receipt"),
            Features.ranked(w, Features.recordUse(emptyMap(), "banner")))
    }

    @Test fun unknownKeysAreIgnored() {
        assertEquals(Features.ranked(w), Features.ranked(w, mapOf("gone" to 50.0)))
    }
}

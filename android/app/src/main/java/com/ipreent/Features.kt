package com.ipreent

/**
 * Which tools people reach for most, so the home screen can put them first. Port of ipreent/features.py.
 *
 * Each tool has a prior weight (a guess at how often it's used; they add up to 1). Every use adds to a
 * decayed count, so the order slowly follows what this person really prints. The app works the order
 * out once when it starts, never while someone is looking at it: tools that move under the finger are
 * worse than a fixed order (split-menu research: Sears & Shneiderman 1994, Findlater & McGrenere 2004).
 */
object Features {
    const val DECAY = 0.9
    const val PRIOR_SCALE = 10.0   // counts level off at 1 / (1 - DECAY) = 10, so habit can outweigh the guess

    /** Android tools. Photos and documents first (what these printers are bought for), then notes, receipts,
     *  templates (cards, tags, journal stickers), checklists, QR/barcodes for labels, and banners (fun, but occasional). */
    val ANDROID = linkedMapOf("photo" to 0.22, "document" to 0.19, "text" to 0.16, "receipt" to 0.13,
        "template" to 0.10, "list" to 0.09, "code" to 0.07, "banner" to 0.04)

    fun recordUse(usage: Map<String, Double>, key: String, decay: Double = DECAY): Map<String, Double> {
        val out = usage.mapValues { it.value * decay }.toMutableMap()
        out[key] = (out[key] ?: 0.0) + 1.0
        return out
    }

    fun score(weights: Map<String, Double>, usage: Map<String, Double>, key: String) =
        PRIOR_SCALE * (weights[key] ?: 0.0) + (usage[key] ?: 0.0)

    /** Keys of [weights], most likely first. Ties keep the prior order. */
    fun ranked(weights: Map<String, Double>, usage: Map<String, Double> = emptyMap()): List<String> =
        weights.keys.sortedWith(compareBy<String>({ -score(weights, usage, it) }, { -(weights[it] ?: 0.0) }, { it }))
}

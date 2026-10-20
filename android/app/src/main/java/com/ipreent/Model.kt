package com.ipreent

import org.json.JSONArray

/** Printer model parameters, extracted from the vendor app (models.json). Port of ipreent/models.py. */
data class Model(
    val name: String = "generic",
    val width: Int = 384,
    val dpi: Int = 200,
    val imgSpeed: Int = 30,
    val textSpeed: Int = 25,
    val energy: Int = 0,
    val rle: Boolean = false,
    val newFormat: Boolean = false,
    val mtu: Int = 123,
    val intervalMs: Int = 6,
    val useSpp: Boolean = false,
) {
    companion object {
        /** Longest modelNo that prefixes the advertised name, like the vendor app. */
        fun lookup(table: JSONArray, bleName: String?): Model {
            if (bleName.isNullOrEmpty()) return Model()
            var best: org.json.JSONObject? = null
            for (i in 0 until table.length()) {
                val m = table.getJSONObject(i)
                val no = m.getString("modelNo")
                if (no.isNotEmpty() && bleName.startsWith(no) &&
                    (best == null || no.length > best.getString("modelNo").length)) best = m
            }
            val b = best ?: return Model()
            return Model(
                name = b.getString("modelNo"),
                width = if (b.getInt("size") == 2) b.getInt("printSize") else b.getInt("paperSize"),
                dpi = b.getInt("dpi"),
                imgSpeed = b.getInt("imgSpeed"),
                textSpeed = b.getInt("textSpeed"),
                energy = b.opt("midEnergy") as? Int ?: 0,
                rle = b.optBoolean("newCompress"),
                newFormat = b.optBoolean("newFormat"),
                mtu = b.optInt("mtu").takeIf { it > 0 } ?: 123,
                intervalMs = b.optInt("interval").takeIf { it > 0 } ?: 6,
                useSpp = b.optBoolean("useSPP"),
            )
        }
    }
}

/** Energy presets, tuned on an SC03h (2026-10-20). */
enum class Darkness(val label: String, val energy: Int) {
    LIGHTEST("Lightest", 5000), LIGHTER("Lighter", 6000), NORMAL("Normal", 8000),
    DARKER("Darker", 12000), DARKEST("Darkest", 17000),
}

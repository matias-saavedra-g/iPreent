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
    val paper: Int = 2,          // vendor "size": paper class (see PAPER)
    val labels: Boolean = false, // vendor "canPrintLabel": has a mode for die-cut labels
) {
    /** What a person needs to know about the printer (port of models.details: same lines, same omissions). */
    fun details(): List<Pair<String, String>> {
        val mm = width * 25.4 / dpi
        val paperName = PAPER[paper] ?: "thermal paper wider than the print width"
        return listOfNotNull(
            "Paper" to paperName,
            if (labels) "Labels" to "die-cut labels supported" else null,
            "Print width" to "${"%.1f".format(java.util.Locale.ROOT, mm)} mm ($width dots)",
            "Resolution" to "$dpi dpi (${"%.0f".format(java.util.Locale.ROOT, dpi / 25.4)} dots per mm)",
        )
    }

    companion object {
        /** Vendor "size" codes, named from the print widths each has in models.json (see models.py). */
        val PAPER = mapOf(1 to "narrow label tape (about 15 mm)", 2 to "57 mm thermal roll (sold as 57 or 58 mm)",
            3 to "80 mm thermal roll", 4 to "4-inch thermal labels or roll (about 110 mm)", 8 to "A4 thermal paper")

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
                paper = b.optInt("size", 2),
                labels = b.optBoolean("canPrintLabel"),
            )
        }
    }
}

/** Energy presets, tuned on an SC03h (2026-10-20). */
enum class Darkness(val label: String, val energy: Int) {
    LIGHTEST("Lightest", 5000), LIGHTER("Lighter", 6000), NORMAL("Normal", 8000),
    DARKER("Darker", 12000), DARKEST("Darkest", 17000),
}

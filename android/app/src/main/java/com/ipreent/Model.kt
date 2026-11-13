package com.ipreent

import android.content.Context
import androidx.annotation.StringRes
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

    /** The same lines as [details], in the app's language (the screens use this one; tests and the Python twin use English). */
    fun details(ctx: Context): List<Pair<String, String>> {
        val mm = width * 25.4 / dpi
        fun t(id: Int, vararg a: Any) = Lang.str(ctx, id, *a)
        return listOfNotNull(
            t(R.string.detail_paper) to t(PAPER_RES[paper] ?: R.string.paper_unknown),
            if (labels) t(R.string.detail_labels) to t(R.string.detail_labels_value) else null,
            t(R.string.detail_print_width) to t(R.string.detail_width_value, "%.1f".format(mm), width),
            t(R.string.detail_resolution) to t(R.string.detail_resolution_value, dpi, "%.0f".format(dpi / 25.4)),
        )
    }

    companion object {
        private val PAPER_RES = mapOf(1 to R.string.paper_1, 2 to R.string.paper_2, 3 to R.string.paper_3,
            4 to R.string.paper_4, 8 to R.string.paper_8)

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
enum class Darkness(@StringRes val label: Int, val energy: Int) {
    LIGHTEST(R.string.darkness_lightest, 5000), LIGHTER(R.string.darkness_lighter, 6000), NORMAL(R.string.darkness_normal, 8000),
    DARKER(R.string.darkness_darker, 12000), DARKEST(R.string.darkness_darkest, 17000),
}

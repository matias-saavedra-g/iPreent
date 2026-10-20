package com.ipreent

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import java.io.File

/** One print, ready to send: the exact rows plus how to print them. */
class Job(val title: String, val rows: List<ByteArray>, val width: Int, val mode: Int = Protocol.MODE_IMAGE, val copies: Int = 1)

data class HistoryItem(val file: File, val title: String, val mode: Int) {
    val time get() = file.lastModified()
}

/**
 * App-wide printer state: model table, remembered printer, a print queue (one job at a time) and history.
 * Port of the connect/print logic in ipreent/api.py, BLE only for now.
 */
object Printers {
    private lateinit var app: Context
    private lateinit var table: JSONArray
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val lock = Mutex()

    val status = MutableStateFlow("Idle")
    val progress = MutableStateFlow<Float?>(null)
    val queued = MutableStateFlow(0)
    val history = MutableStateFlow<List<HistoryItem>>(emptyList())

    private val _darkness = MutableStateFlow(Darkness.NORMAL)
    val darkness = _darkness.asStateFlow()

    fun init(ctx: Context) {
        if (::app.isInitialized) return
        app = ctx.applicationContext
        table = JSONArray(app.assets.open("models.json").bufferedReader().readText())
        _darkness.value = Darkness.entries.getOrNull(prefs.getInt("darkness", Darkness.NORMAL.ordinal)) ?: Darkness.NORMAL
        loadHistory()
    }

    private val prefs get() = app.getSharedPreferences("printer", Context.MODE_PRIVATE)
    private val historyDir get() = File(app.filesDir, "history").apply { mkdirs() }

    val savedName: String? get() = prefs.getString("name", null)
    val savedAddress: String? get() = prefs.getString("address", null)
    fun remember(f: Found) = prefs.edit().putString("name", f.name).putString("address", f.address).apply()
    fun forget() = prefs.edit().remove("name").remove("address").apply()
    fun setDarkness(d: Darkness) { _darkness.value = d; prefs.edit().putInt("darkness", d.ordinal).apply() }

    fun model(name: String? = savedName) = Model.lookup(table, name)
    fun isKnown(name: String) = model(name).name != "generic"
    /** Paper width for layout, before we are connected. */
    val width get() = model().width

    suspend fun scan(): List<Found> = BlePrinter.scan(app, ::isKnown)

    /** Run [block] with a connected printer: remembered one first, then a fresh scan. */
    private suspend fun <T> withPrinter(block: suspend (BlePrinter) -> T): T {
        var lastErr: Throwable? = null
        val candidates = listOfNotNull(savedAddress?.let { Found(savedName ?: "", it) }) + listOf(null)
        for (c in candidates) {
            var f = c
            if (f == null) {
                status.value = "Scanning…"
                f = scan().firstOrNull() ?: break
            }
            status.value = "Connecting to ${f.name.ifEmpty { f.address }}…"
            val p = try { BlePrinter.connect(app, f.address, model(f.name)) } catch (e: Throwable) { lastErr = e; continue }
            remember(f)
            try { return block(p) } finally { p.close() }
        }
        throw IllegalStateException(lastErr?.message ?: "No printer found. Is it on and not connected to another app?")
    }

    /** Queue a job. Jobs print one after another; the returned Deferred completes when this one is done. */
    fun enqueue(job: Job, saveToHistory: Boolean = true): Deferred<Unit> {
        queued.value++
        if (saveToHistory) save(job)
        return scope.async {
            try {
                lock.withLock {
                    withPrinter { p ->
                        val bytes = Protocol.printJob(job.rows, p.model, darkness.value.energy, job.mode)
                        repeat(job.copies) { n ->
                            status.value = "Printing ${job.title}" + if (job.copies > 1) " (${n + 1}/${job.copies})" else ""
                            p.send(bytes) { progress.value = it }
                            p.waitDone()
                        }
                    }
                    status.value = "Done"
                }
            } catch (e: Throwable) {
                status.value = "Error: ${e.message}"
                throw e
            } finally {
                progress.value = null
                queued.value--
            }
        }
    }

    suspend fun readStatus(): String = lock.withLock {
        withPrinter { p ->
            val st = p.request(Protocol.CMD_GET_STATE)
            val bat = p.request(Protocol.CMD_BATTERY)
            "${p.model.name}: ${Protocol.describeState(st)}" + (bat?.let { " · battery ${it[0].toInt() and 0xFF}%" } ?: "")
        }.also { status.value = it }
    }

    // ---- history: each job saved as the exact 1-bit PNG that was printed -------------------------

    private fun save(job: Job) {
        val safe = job.title.replace(Regex("[^A-Za-z0-9 _-]"), "").take(40).ifBlank { "print" }
        val f = File(historyDir, "${System.currentTimeMillis()}_${job.mode}_$safe.png")
        f.outputStream().use { Imaging.preview(job.rows, job.width).compress(Bitmap.CompressFormat.PNG, 100, it) }
        historyDir.listFiles()!!.sortedByDescending { it.lastModified() }.drop(50).forEach { it.delete() }
        loadHistory()
    }

    private fun loadHistory() {
        history.value = historyDir.listFiles().orEmpty().sortedByDescending { it.lastModified() }.map {
            val parts = it.nameWithoutExtension.split("_", limit = 3)
            HistoryItem(it, parts.getOrElse(2) { "print" }, parts.getOrNull(1)?.toIntOrNull() ?: Protocol.MODE_IMAGE)
        }
    }

    fun deleteHistory(item: HistoryItem) { item.file.delete(); loadHistory() }

    fun reprint(item: HistoryItem): Deferred<Unit> {
        val bmp = BitmapFactory.decodeFile(item.file.path)
        val (g, h) = Imaging.toGray(bmp, bmp.width, autoRotate = false)
        return enqueue(Job(item.title, Imaging.rows(g, bmp.width, h, Dither.THRESHOLD), bmp.width, item.mode), saveToHistory = false)
    }
}

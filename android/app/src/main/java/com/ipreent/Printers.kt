package com.ipreent

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

/** One print, ready to send: the exact rows plus how to print them. */
class Job(val title: String, val rows: List<ByteArray>, val width: Int, val mode: Int = Protocol.MODE_IMAGE, val copies: Int = 1)

data class HistoryItem(val file: File, val title: String, val mode: Int) {
    val time get() = file.lastModified()
}

enum class JobState { WAITING, CONNECTING, PRINTING, DONE, FAILED, CANCELLED }

/** One line in the print queue. [seconds] is the estimate, counted from [startedAt] once the job starts. */
data class QueueEntry(
    val id: Int,
    val title: String,
    val thumb: Bitmap?,
    val lines: Int,
    val copies: Int,
    val seconds: Double,
    val state: JobState = JobState.WAITING,
    val startedAt: Long = 0L,
    val progress: Float = 0f,
    val copy: Int = 1,
    val finishedAt: Long = 0L,
    val error: String? = null,
) {
    val active get() = state == JobState.WAITING || state == JobState.CONNECTING || state == JobState.PRINTING
    fun remaining(now: Long): Double = if (startedAt == 0L) seconds else maxOf(0.0, seconds - (now - startedAt) / 1000.0)
    /** 0..1 by the clock (smoother than bytes sent: the printer keeps going after the last byte). */
    fun timeFraction(now: Long): Float = if (seconds <= 0) 0f else (1 - remaining(now) / seconds).toFloat().coerceIn(0f, 1f)
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

    /** One line about what the printer is doing, in the app's language (set again when the language changes). */
    val status = MutableStateFlow("")
    val history = MutableStateFlow<List<HistoryItem>>(emptyList())
    /** Waiting and printing jobs plus the last few finished ones, oldest first. */
    val queue = MutableStateFlow<List<QueueEntry>>(emptyList())
    private val running = ConcurrentHashMap<Int, Deferred<Unit>>()
    private val ids = AtomicInteger(1)
    private val _printerName = MutableStateFlow<String?>(null)
    /** Name of the remembered printer, for the top bar. */
    val printerName = _printerName.asStateFlow()

    private val _darkness = MutableStateFlow(Darkness.NORMAL)
    val darkness = _darkness.asStateFlow()

    fun init(ctx: Context) {
        if (::app.isInitialized) return
        app = ctx.applicationContext
        table = JSONArray(app.assets.open("models.json").bufferedReader().readText())
        _darkness.value = Darkness.entries.getOrNull(prefs.getInt("darkness", Darkness.NORMAL.ordinal)) ?: Darkness.NORMAL
        _printerName.value = savedName
        status.value = s(R.string.status_idle)
        _debugSpeed.value = prefs.getFloat("debug_mm_per_s", 0f).toDouble().takeIf { it > 0 }
        loadHistory()
    }

    private fun s(id: Int, vararg args: Any) = Lang.str(app, id, *args)

    /** The language was changed in the debug settings: redo the texts that are kept as strings. */
    fun languageChanged() { if (!busy) status.value = s(R.string.status_idle) }

    private val prefs get() = app.getSharedPreferences("printer", Context.MODE_PRIVATE)
    private val historyDir get() = File(app.filesDir, "history").apply { mkdirs() }

    val savedName: String? get() = prefs.getString("name", null)
    val savedAddress: String? get() = prefs.getString("address", null)
    fun remember(f: Found) {
        prefs.edit().putString("name", f.name).putString("address", f.address).apply()
        _printerName.value = f.name.ifEmpty { f.address }
    }
    fun forget() { prefs.edit().remove("name").remove("address").apply(); _printerName.value = null }
    fun setDarkness(d: Darkness) { _darkness.value = d; prefs.edit().putInt("darkness", d.ordinal).apply() }

    fun model(name: String? = savedName) = Model.lookup(table, name)
    fun isKnown(name: String) = model(name).name != "generic"
    /** Paper width for layout, before we are connected. */
    val width get() = model().width

    // ---- print time: the slowest nominal speed, or the debug setting ---------------------------
    // Timed prints no longer change the estimate (they weren't reliable); the last one's measured speed is kept
    // only to show in the debug settings. Old learnt "speeds" / "mm_per_s" are ignored and dropped.
    private val _debugSpeed = MutableStateFlow<Double?>(null)    // loaded in init
    /** The debug paper speed in mm/s, or null when estimates use [Protocol.NOMINAL_MM_PER_S]. */
    val debugSpeed = _debugSpeed.asStateFlow()
    fun setDebugSpeed(mmPerS: Double?) {
        val v = mmPerS?.takeIf { it > 0 && kotlin.math.abs(it - Protocol.NOMINAL_MM_PER_S) > 1e-9 }?.let { Protocol.speedFor(it) }
        prefs.edit().apply { if (v == null) remove("debug_mm_per_s") else putFloat("debug_mm_per_s", v.toFloat()) }
            .remove("speeds").remove("mm_per_s").apply()
        _debugSpeed.value = v
    }
    var debugUnlocked: Boolean
        get() = prefs.getBoolean("debug_unlocked", false)
        set(v) { prefs.edit().putBoolean("debug_unlocked", v).apply() }
    /** mm/s the last long-enough timed print showed (debug settings only), or null. */
    val lastMeasuredSpeed: Double? get() = prefs.getFloat("last_measured_mm_per_s", 0f).toDouble().takeIf { it > 0 }

    /** mm/s used for estimates (the same at every darkness). */
    fun speed() = Protocol.speedFor(_debugSpeed.value)

    fun estimate(lines: Int, copies: Int = 1, connect: Boolean = true, mmPerS: Double = speed()) =
        Protocol.estimateSeconds(lines, model().dpi, copies, mmPerS, connect = connect)

    private fun logTiming(lines: Int, dpi: Int, copies: Int, seconds: Double) {
        val v = Protocol.measuredSpeed(lines, dpi, copies, seconds) ?: return
        prefs.edit().putFloat("last_measured_mm_per_s", v.toFloat()).remove("speeds").remove("mm_per_s").apply()
    }

    val busy get() = queue.value.any { it.active }

    /** Seconds until everything queued has printed. */
    fun queueRemaining(now: Long = System.currentTimeMillis()) = queue.value.filter { it.active }.sumOf { it.remaining(now) }

    private fun update(id: Int, f: (QueueEntry) -> QueueEntry) = queue.update { l -> l.map { if (it.id == id) f(it) else it } }

    /** Remove a job that hasn't started yet. */
    fun cancel(id: Int) { if (queue.value.any { it.id == id && it.state == JobState.WAITING }) running[id]?.cancel() }

    fun clearFinished() = queue.update { l -> l.filter { it.active } }

    suspend fun scan(): List<Found> = BlePrinter.scan(app, ::isKnown)

    /** Run [block] with a connected printer: remembered one first, then a fresh scan. */
    private suspend fun <T> withPrinter(block: suspend (BlePrinter) -> T): T {
        var lastErr: Throwable? = null
        val candidates = listOfNotNull(savedAddress?.let { Found(savedName ?: "", it) }) + listOf(null)
        for (c in candidates) {
            var f = c
            if (f == null) {
                status.value = s(R.string.status_scanning)
                f = scan().firstOrNull() ?: break
            }
            status.value = s(R.string.status_connecting, f.name.ifEmpty { f.address })
            val p = try { BlePrinter.connect(app, f.address, model(f.name)) } catch (e: Throwable) { lastErr = e; continue }
            remember(f)
            try { return block(p) } finally { p.close() }
        }
        throw lastErr ?: UserError(R.string.err_no_printer, emptyList(), "No printer found. Is it on and not connected to another app?")
    }

    /** Queue a job. Jobs print one after another; the returned Deferred completes when this one is done. */
    fun enqueue(job: Job, saveToHistory: Boolean = true): Deferred<Unit> {
        val id = ids.getAndIncrement()
        val picture = Imaging.preview(job.rows, job.width)
        if (saveToHistory) save(job, picture)
        val thumb = Bitmap.createScaledBitmap(picture, 96, maxOf(1, picture.height * 96 / picture.width), false)
        val entry = QueueEntry(id, job.title, thumb, job.rows.size, job.copies, estimate(job.rows.size, job.copies))
        queue.update { l -> (l + entry).let { all -> all.filter { it.active } + all.filterNot { it.active }.takeLast(20) }.sortedBy { it.id } }
        val d = scope.async(start = CoroutineStart.LAZY) {
            try {
                lock.withLock {
                    update(id) { it.copy(state = JobState.CONNECTING, startedAt = System.currentTimeMillis()) }
                    withPrinter { p ->
                        val energy = darkness.value.energy
                        val bytes = Protocol.printJob(job.rows, p.model, energy, job.mode)
                        val secs = Protocol.estimateSeconds(job.rows.size, p.model.dpi, job.copies, speed(), connect = false)
                        val t0 = System.currentTimeMillis()
                        update(id) { it.copy(state = JobState.PRINTING, seconds = secs, startedAt = t0) }
                        repeat(job.copies) { n ->
                            status.value = if (job.copies > 1) s(R.string.status_printing_copies, job.title, n + 1, job.copies) else s(R.string.status_printing, job.title)
                            update(id) { it.copy(copy = n + 1, progress = 0f) }
                            var shown = 0
                            p.send(bytes) { f ->
                                val pct = (f * 100).toInt()
                                if (pct != shown) { shown = pct; update(id) { it.copy(progress = f) } }
                            }
                            p.waitDone()
                        }
                        logTiming(job.rows.size, p.model.dpi, job.copies, (System.currentTimeMillis() - t0) / 1000.0)
                    }
                    status.value = s(R.string.status_done)
                }
                update(id) { it.copy(state = JobState.DONE, finishedAt = System.currentTimeMillis()) }
            } catch (e: CancellationException) {
                update(id) { it.copy(state = JobState.CANCELLED, finishedAt = System.currentTimeMillis()) }
                throw e
            } catch (e: Throwable) {
                val text = Lang.text(app, e)
                status.value = s(R.string.status_error, text)
                update(id) { it.copy(state = JobState.FAILED, error = text, finishedAt = System.currentTimeMillis()) }
                throw e
            } finally {
                running.remove(id)
            }
        }
        running[id] = d
        d.start()
        return d
    }

    private val STATE_WORDS = mapOf("out of paper" to R.string.printer_state_out_of_paper, "cover open" to R.string.printer_state_cover_open,
        "overheated" to R.string.printer_state_overheated, "low battery" to R.string.printer_state_low_battery,
        "charging" to R.string.printer_state_charging, "printing" to R.string.printer_state_printing,
        "ready" to R.string.printer_state_ready, "unknown" to R.string.printer_state_unknown)

    suspend fun readStatus(): String = lock.withLock {
        withPrinter { p ->
            val st = p.request(Protocol.CMD_GET_STATE)
            val bat = p.request(Protocol.CMD_BATTERY)
            val state = Protocol.describeState(st) { w -> s(STATE_WORDS.getValue(w)) }
            bat?.let { s(R.string.status_battery, p.model.name, state, it[0].toInt() and 0xFF) } ?: s(R.string.status_state, p.model.name, state)
        }.also { status.value = it }
    }

    // ---- history: each job saved as the exact 1-bit PNG that was printed -------------------------

    private fun save(job: Job, picture: Bitmap) {
        val safe = job.title.replace(Regex("[^\\p{L}\\p{N} _-]"), "").take(40).ifBlank { "print" }
        val f = File(historyDir, "${System.currentTimeMillis()}_${job.mode}_$safe.png")
        f.outputStream().use { picture.compress(Bitmap.CompressFormat.PNG, 100, it) }
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

    /** The exact print a history entry saved, ready to queue again. */
    fun reprintJob(item: HistoryItem): Job {
        val bmp = BitmapFactory.decodeFile(item.file.path)
        val (g, h) = Imaging.toGray(bmp, bmp.width, autoRotate = false)
        return Job(item.title, Imaging.rows(g, bmp.width, h, Dither.THRESHOLD), bmp.width, item.mode)
    }
}

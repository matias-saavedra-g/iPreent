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

    val status = MutableStateFlow("Idle")
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
        loadHistory()
    }

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

    // ---- print time: starts at the listing's speed, learns from each timed print --------------

    val speed: Double get() = prefs.getFloat("mm_per_s", Protocol.SPEC_MM_PER_S.toFloat()).toDouble()
    val timedPrints: Int get() = prefs.getInt("timed_prints", 0)

    fun estimate(lines: Int, copies: Int = 1, connect: Boolean = true) =
        Protocol.estimateSeconds(lines, model().dpi, copies, speed, connect = connect)

    private fun learn(lines: Int, dpi: Int, copies: Int, seconds: Double) {
        val v = Protocol.learnSpeed(speed, lines, dpi, copies, seconds)
        prefs.edit().putFloat("mm_per_s", v.toFloat()).putInt("timed_prints", timedPrints + 1).apply()
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
                        val bytes = Protocol.printJob(job.rows, p.model, darkness.value.energy, job.mode)
                        val secs = Protocol.estimateSeconds(job.rows.size, p.model.dpi, job.copies, speed, connect = false)
                        val t0 = System.currentTimeMillis()
                        update(id) { it.copy(state = JobState.PRINTING, seconds = secs, startedAt = t0) }
                        repeat(job.copies) { n ->
                            status.value = "Printing ${job.title}" + if (job.copies > 1) " (${n + 1}/${job.copies})" else ""
                            update(id) { it.copy(copy = n + 1, progress = 0f) }
                            var shown = 0
                            p.send(bytes) { f ->
                                val pct = (f * 100).toInt()
                                if (pct != shown) { shown = pct; update(id) { it.copy(progress = f) } }
                            }
                            p.waitDone()
                        }
                        learn(job.rows.size, p.model.dpi, job.copies, (System.currentTimeMillis() - t0) / 1000.0)
                    }
                    status.value = "Done"
                }
                update(id) { it.copy(state = JobState.DONE, finishedAt = System.currentTimeMillis()) }
            } catch (e: CancellationException) {
                update(id) { it.copy(state = JobState.CANCELLED, finishedAt = System.currentTimeMillis()) }
                throw e
            } catch (e: Throwable) {
                status.value = "Error: ${e.message}"
                update(id) { it.copy(state = JobState.FAILED, error = e.message ?: "failed", finishedAt = System.currentTimeMillis()) }
                throw e
            } finally {
                running.remove(id)
            }
        }
        running[id] = d
        d.start()
        return d
    }

    suspend fun readStatus(): String = lock.withLock {
        withPrinter { p ->
            val st = p.request(Protocol.CMD_GET_STATE)
            val bat = p.request(Protocol.CMD_BATTERY)
            "${p.model.name}: ${Protocol.describeState(st)}" + (bat?.let { " · battery ${it[0].toInt() and 0xFF}%" } ?: "")
        }.also { status.value = it }
    }

    // ---- history: each job saved as the exact 1-bit PNG that was printed -------------------------

    private fun save(job: Job, picture: Bitmap) {
        val safe = job.title.replace(Regex("[^A-Za-z0-9 _-]"), "").take(40).ifBlank { "print" }
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

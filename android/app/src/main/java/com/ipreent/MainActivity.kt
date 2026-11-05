package com.ipreent

import android.Manifest
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.isSpecified
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import com.google.zxing.BarcodeFormat
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.text.DateFormat
import java.util.Date
import kotlin.math.roundToInt

private val BabyBlue = Color(0xFF89CFF0)
private val DeepBlue = Color(0xFF4A90B8)

class MainActivity : ComponentActivity() {
    /** Content shared from another app, consumed once by the UI. */
    private val shared = mutableStateOf<Sources.Loaded?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Printers.init(this)
        handle(intent)
        setContent {
            val dark = androidx.compose.foundation.isSystemInDarkTheme()
            // Material You: wallpaper colours on Android 12+, brand baby blue before that. Follows the system theme.
            val scheme = when {
                Build.VERSION.SDK_INT >= 31 -> if (dark) dynamicDarkColorScheme(this) else dynamicLightColorScheme(this)
                dark -> darkColorScheme(primary = BabyBlue, onPrimary = Color(0xFF00344C), primaryContainer = Color(0xFF1F5878))
                else -> lightColorScheme(primary = DeepBlue, primaryContainer = BabyBlue, onPrimaryContainer = Color(0xFF00344C))
            }
            MaterialTheme(colorScheme = scheme) { App(shared) }
        }
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); handle(intent) }

    private fun handle(intent: Intent?) {
        if (intent?.action != Intent.ACTION_SEND) return
        val text = intent.getStringExtra(Intent.EXTRA_TEXT)
        @Suppress("DEPRECATION")
        val uri = intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)
        Thread {
            shared.value = try {
                if (uri != null) Sources.load(this, uri, Printers.width) else text?.let { Sources.Loaded.Text(it) }
            } catch (e: Exception) { Sources.Loaded.Text("Could not open shared file: ${e.message}") }
        }.start()
    }
}

private val PERMS = if (Build.VERSION.SDK_INT >= 31)
    arrayOf(Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT)
else arrayOf(Manifest.permission.ACCESS_FINE_LOCATION)

/** Everything the app can print. Order on the home screen comes from [Features.ANDROID] weights + usage. */
private enum class Tool(val key: String, val label: String, val blurb: String, val icon: ImageVector) {
    PHOTO("photo", "Photo", "From your gallery", Icons.Default.Image),
    DOCUMENT("document", "Document", "PDFs, sharp text", Icons.Default.Description),
    TEXT("text", "Text", "Notes and messages", Icons.Default.TextFields),
    RECEIPT("receipt", "Receipt", "Boleta with total and barcode", Icons.Default.Receipt),
    LIST("list", "Checklist", "To-do lists with boxes", Icons.Default.Checklist),
    CODE("code", "QR & barcode", "Links, labels, product codes", Icons.Default.QrCode2),
    BANNER("banner", "Banner", "Big text along the paper", Icons.Default.ViewDay);

    companion object { fun of(key: String) = entries.first { it.key == key } }
}

/** The three top-level destinations: Material 3 asks for 3-5 in a navigation bar. */
private enum class Dest(val label: String, val icon: ImageVector) {
    CREATE("Create", Icons.Default.Apps), QUEUE("Queue", Icons.Default.Print), HISTORY("History", Icons.Default.History)
}

/** How often each tool is used (decayed counts), and the home-screen order worked out once per run. */
private object Usage {
    private var order: List<Tool>? = null
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("usage", Context.MODE_PRIVATE)
    private fun load(ctx: Context): Map<String, Double> = runCatching {
        val o = JSONObject(prefs(ctx).getString("counts", "{}")!!)
        o.keys().asSequence().associateWith { o.getDouble(it) }
    }.getOrDefault(emptyMap())

    /** Fixed for the whole run, so tiles never move while you look at them. */
    fun order(ctx: Context) = order ?: Features.ranked(Features.ANDROID, load(ctx)).map(Tool::of).also { order = it }

    fun record(ctx: Context, tool: Tool) {
        prefs(ctx).edit().putString("counts", JSONObject(Features.recordUse(load(ctx), tool.key)).toString()).apply()
    }
}

/** A paper slip that flies from the Print button to the Queue tab when a job is added. */
private class Fly {
    var from by mutableStateOf(Offset.Unspecified)
    var to by mutableStateOf(Offset.Unspecified)
    val t = Animatable(0f)
    var flying by mutableStateOf(false)
    var landed by mutableIntStateOf(0)

    suspend fun go() {
        if (from.isSpecified && to.isSpecified) {
            flying = true
            t.snapTo(0f)
            t.animateTo(1f, tween(700, easing = FastOutSlowInEasing))
            flying = false
        }
        landed++
    }
}

private val LocalFly = staticCompositionLocalOf { Fly() }

/** Wall clock that ticks twice a second while shown, for countdowns. */
@Composable
private fun rememberNow(): Long {
    val now by produceState(System.currentTimeMillis()) { while (isActive) { value = System.currentTimeMillis(); delay(500) } }
    return now
}

private fun eta(seconds: Double) = Protocol.formatEta(seconds)

/** "about 0:12 left", or "finishing" once the estimate has run out but the printer hasn't said it's done. */
private fun left(e: QueueEntry, now: Long) = e.remaining(now).let { if (it > 0) "about ${eta(it)} left" else "finishing" }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun App(shared: MutableState<Sources.Loaded?>) {
    val ctx = LocalContext.current
    val order = remember { Usage.order(ctx) }
    var dest by rememberSaveable { mutableStateOf(Dest.CREATE) }
    var tool by rememberSaveable { mutableStateOf<Tool?>(null) }
    var photo by remember { mutableStateOf<List<Bitmap>>(emptyList()) }
    var docs by remember { mutableStateOf<List<Bitmap>>(emptyList()) }
    var text by remember { mutableStateOf("") }
    var pending by remember { mutableStateOf<Pair<Job, Boolean>?>(null) }     // job, save to history
    var sheet by remember { mutableStateOf(false) }
    val snack = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val fly = remember { Fly() }
    val queue by Printers.queue.collectAsState()
    val active = queue.count { it.active }
    var granted by remember { mutableStateOf(false) }
    val askPerms = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { r ->
        granted = r.values.all { it }
    }
    LaunchedEffect(Unit) { askPerms.launch(PERMS) }

    shared.value?.let { s ->
        when (s) {
            is Sources.Loaded.Pages -> if (s.document) { docs = s.bitmaps; tool = Tool.DOCUMENT } else { photo = s.bitmaps; tool = Tool.PHOTO }
            is Sources.Loaded.Text -> { text = s.text; tool = Tool.TEXT }
        }
        dest = Dest.CREATE
        shared.value = null
    }

    fun submit(job: Job, save: Boolean = true) {
        if (save) tool?.let { Usage.record(ctx, it) }
        scope.launch { fly.go() }
        scope.launch {
            try { Printers.enqueue(job, saveToHistory = save).await(); snack.showSnackbar("Printed “${job.title}”") }
            catch (e: CancellationException) { if (isActive) snack.showSnackbar("Removed “${job.title}” from the queue") else throw e }
            catch (e: Throwable) { snack.showSnackbar(e.message ?: "Print failed") }
        }
    }
    // Something already printing? Ask first: the printer's own progress is easy to miss.
    fun print(job: Job, save: Boolean) {
        when {
            !granted -> askPerms.launch(PERMS)
            Printers.busy -> pending = job to save
            else -> submit(job, save)
        }
    }
    val print: (Job) -> Unit = { print(it, true) }

    BackHandler(dest == Dest.CREATE && tool != null) { tool = null }
    BackHandler(dest != Dest.CREATE) { dest = Dest.CREATE }

    CompositionLocalProvider(LocalFly provides fly) {
        Box(Modifier.fillMaxSize()) {
            Scaffold(
                topBar = {
                    val t = tool.takeIf { dest == Dest.CREATE }
                    TopAppBar(
                        title = { Text(t?.label ?: if (dest == Dest.CREATE) "iPreent" else dest.label, fontWeight = FontWeight.Bold) },
                        navigationIcon = {
                            if (t != null) IconButton({ tool = null }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back to all tools") }
                        },
                        actions = { PrinterChip(active > 0) { sheet = true } },
                    )
                },
                bottomBar = {
                    NavigationBar {
                        Dest.entries.forEach { d ->
                            NavigationBarItem(
                                selected = dest == d,
                                onClick = { if (d == Dest.CREATE && dest == Dest.CREATE) tool = null; dest = d },
                                icon = { if (d == Dest.QUEUE) QueueIcon(active) else Icon(d.icon, null) },
                                label = { Text(d.label) },
                            )
                        }
                    }
                },
                snackbarHost = { SnackbarHost(snack) },
            ) { pad ->
                Column(Modifier.padding(pad).fillMaxSize()) {
                    if (dest == Dest.CREATE) NowPrinting(queue) { dest = Dest.QUEUE }
                    Box(Modifier.weight(1f)) {
                        when (dest) {
                            Dest.QUEUE -> QueueScreen(queue)
                            Dest.HISTORY -> HistoryTab { print(Printers.reprintJob(it), false) }
                            Dest.CREATE -> when (tool) {
                                null -> HomeScreen(order) { tool = it }
                                Tool.PHOTO -> ImageTab(false, photo, { photo = it }, print)
                                Tool.DOCUMENT -> ImageTab(true, docs, { docs = it }, print)
                                Tool.TEXT -> TextTab(text, { text = it }, print)
                                Tool.LIST -> ListTab(print)
                                Tool.BANNER -> BannerTab(print)
                                Tool.CODE -> CodeTab(print)
                                Tool.RECEIPT -> ReceiptTab(print)
                            }
                        }
                    }
                }
            }
            FlyingSlip(fly)
        }
    }

    pending?.let { (job, save) -> BusyDialog(job, onAdd = { pending = null; submit(job, save) }, onCancel = { pending = null }) }
    if (sheet) PrinterSheet(granted, snack) { sheet = false }
}

@Composable
private fun QueueIcon(active: Int) {
    val fly = LocalFly.current
    val pulse = remember { Animatable(1f) }
    LaunchedEffect(fly.landed) {
        if (fly.landed > 0) {
            pulse.animateTo(1.35f, tween(140))
            pulse.animateTo(1f, spring(dampingRatio = Spring.DampingRatioMediumBouncy))
        }
    }
    BadgedBox(badge = { if (active > 0) Badge { Text("$active") } },
        modifier = Modifier.onGloballyPositioned { fly.to = it.boundsInRoot().center }
            .graphicsLayer { scaleX = pulse.value; scaleY = pulse.value }) {
        Icon(Dest.QUEUE.icon, null)
    }
}

@Composable
private fun FlyingSlip(fly: Fly) {
    if (!fly.flying) return
    val t = fly.t.value
    val a = fly.from
    val b = fly.to
    val c = Offset((a.x + b.x) / 2, minOf(a.y, b.y) - 220f)       // arc up and over
    val p = a * ((1 - t) * (1 - t)) + c * (2 * (1 - t) * t) + b * (t * t)
    val sizeDp = 36f - 14f * t
    val half = with(LocalDensity.current) { (sizeDp / 2).dp.toPx() }
    Box(
        Modifier.offset { IntOffset((p.x - half).roundToInt(), (p.y - half).roundToInt()) }
            .size(sizeDp.dp)
            .graphicsLayer { rotationZ = -12f * (1 - t); alpha = if (t > 0.92f) (1 - t) / 0.08f else 1f }
            .clip(CircleShape).background(MaterialTheme.colorScheme.primary),
        contentAlignment = Alignment.Center,
    ) { Icon(Icons.Default.Description, null, Modifier.size((sizeDp * 0.55f).dp), tint = MaterialTheme.colorScheme.onPrimary) }
}

@Composable
private fun BusyDialog(job: Job, onAdd: () -> Unit, onCancel: () -> Unit) {
    val now = rememberNow()
    val queue by Printers.queue.collectAsState()
    val active = queue.filter { it.active }
    val cur = active.firstOrNull { it.state != JobState.WAITING } ?: active.firstOrNull()
    if (cur == null) {      // it finished while we were asking
        AlertDialog(onDismissRequest = onCancel, icon = { Icon(Icons.Default.Print, null) },
            title = { Text("The printer is free now") }, text = { Text("Print “${job.title}”?") },
            confirmButton = { TextButton(onAdd) { Text("Print") } }, dismissButton = { TextButton(onCancel) { Text("Cancel") } })
        return
    }
    val left = cur.remaining(now)
    AlertDialog(
        onDismissRequest = onCancel,
        icon = { Icon(Icons.Default.HourglassTop, null) },
        title = { Text("The printer is busy") },
        text = {
            Text(buildString {
                append("“${cur.title}” is printing: ")
                append(if (left > 0) "about ${eta(left)} left." else "almost done.")
                if (active.size > 1) append(" ${active.size - 1} more waiting.")
                append("\n\nAdd “${job.title}” to the queue? It should start in about ${eta(Printers.queueRemaining(now))}")
                append(" and take about ${eta(Printers.estimate(job.rows.size, job.copies))}.")
            })
        },
        confirmButton = { TextButton(onAdd) { Text("Add to queue") } },
        dismissButton = { TextButton(onCancel) { Text("Cancel") } },
    )
}

/** Printer name + gear in the top bar: clearly a button that opens the printer settings. */
@Composable
private fun PrinterChip(printing: Boolean, onClick: () -> Unit) {
    val name by Printers.printerName.collectAsState()
    AssistChip(
        onClick = onClick,
        label = { Text(name ?: "Set up printer", maxLines = 1, overflow = TextOverflow.Ellipsis) },
        leadingIcon = {
            if (printing) CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
            else Icon(Icons.Default.Print, null, Modifier.size(18.dp))
        },
        trailingIcon = { Icon(Icons.Outlined.Settings, "Printer settings", Modifier.size(18.dp)) },
        colors = if (name == null) AssistChipDefaults.assistChipColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
                 else AssistChipDefaults.assistChipColors(),
        modifier = Modifier.padding(end = 8.dp).widthIn(max = 200.dp),
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PrinterSheet(granted: Boolean, snack: SnackbarHostState, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    val name by Printers.printerName.collectAsState()
    val darkness by Printers.darkness.collectAsState()
    val status by Printers.status.collectAsState()
    var found by remember { mutableStateOf<List<Found>?>(null) }
    var scanning by remember { mutableStateOf(false) }
    ModalBottomSheet(onDismissRequest = onClose) {
        Column(Modifier.padding(horizontal = 24.dp).padding(bottom = 24.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(48.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primaryContainer), contentAlignment = Alignment.Center) {
                    Icon(Icons.Default.Print, null, tint = MaterialTheme.colorScheme.onPrimaryContainer)
                }
                Column(Modifier.padding(start = 16.dp).weight(1f)) {
                    Text(name ?: "No printer yet", style = MaterialTheme.typography.titleMedium)
                    Text(if (name == null) "Turn it on; it's found on the first print, or use Find printers."
                         else "${Printers.model().name} · Bluetooth LE · $status",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Spacer(Modifier.height(24.dp))
            Row {
                Text("Darkness", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                Text(darkness.label, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary)
            }
            Slider(darkness.ordinal.toFloat(), { Printers.setDarkness(Darkness.entries[it.roundToInt()]) },
                valueRange = 0f..(Darkness.entries.size - 1).toFloat(), steps = Darkness.entries.size - 2)
            Row {
                Text("Lighter", style = MaterialTheme.typography.labelSmall, modifier = Modifier.weight(1f))
                Text("Darker (prints a little slower)", style = MaterialTheme.typography.labelSmall)
            }
            Spacer(Modifier.height(8.dp))
            Text("Print speed: about ${Printers.speed.roundToInt()} mm/s" +
                    if (Printers.timedPrints > 0) ", learnt from your prints" else " (the listing's figure until a print is timed)",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            HorizontalDivider(Modifier.padding(vertical = 12.dp))
            ListItem(headlineContent = { Text("Check status and battery") },
                leadingContent = { Icon(Icons.Default.BatteryStd, null) },
                modifier = Modifier.clickable(enabled = granted && !Printers.busy) {
                    scope.launch { snack.showSnackbar(runCatching { Printers.readStatus() }.getOrElse { it.message ?: "error" }) }
                    onClose()
                })
            ListItem(headlineContent = { Text(if (scanning) "Looking for printers…" else "Find printers") },
                leadingContent = { if (scanning) CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp) else Icon(Icons.Default.BluetoothSearching, null) },
                modifier = Modifier.clickable(enabled = granted && !scanning) {
                    scanning = true
                    scope.launch {
                        found = runCatching { Printers.scan() }.getOrElse { snack.showSnackbar(it.message ?: "Scan failed"); null }
                        scanning = false
                    }
                })
            if (name != null) ListItem(headlineContent = { Text("Forget this printer") },
                leadingContent = { Icon(Icons.Default.LinkOff, null) },
                modifier = Modifier.clickable { Printers.forget() })
        }
    }
    found?.let { list ->
        AlertDialog(onDismissRequest = { found = null }, confirmButton = { TextButton({ found = null }) { Text("Close") } },
            title = { Text(if (list.isEmpty()) "No printers found" else "Pick a printer") },
            text = {
                Column {
                    if (list.isEmpty()) Text("Is it on, and not connected to another app?")
                    list.forEach { f ->
                        TextButton({ Printers.remember(f); found = null }) { Text("${f.name}  ·  ${f.address}") }
                    }
                }
            })
    }
}

/** Shown above the tools while something prints; tap to open the queue. */
@Composable
private fun NowPrinting(queue: List<QueueEntry>, open: () -> Unit) {
    val active = queue.filter { it.active }
    val cur = active.firstOrNull { it.state != JobState.WAITING } ?: active.firstOrNull() ?: return
    val now = rememberNow()
    Surface(color = MaterialTheme.colorScheme.secondaryContainer, shape = MaterialTheme.shapes.medium,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp).clip(MaterialTheme.shapes.medium).clickable(onClick = open)) {
        Column(Modifier.padding(horizontal = 16.dp, vertical = 10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(stateText(cur, now) + " “${cur.title}”", Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.labelLarge)
                Text(left(cur, now).removePrefix("about ") + if (active.size > 1) " · ${active.size - 1} waiting" else "",
                    style = MaterialTheme.typography.labelMedium)
            }
            LinearProgressIndicator({ cur.timeFraction(now) }, Modifier.fillMaxWidth().padding(top = 6.dp))
        }
    }
}

private fun stateText(e: QueueEntry, now: Long) = when (e.state) {
    JobState.WAITING -> "Waiting:"
    JobState.CONNECTING -> "Connecting:"
    else -> if (e.copies > 1) "Printing ${e.copy}/${e.copies}:" else "Printing"
}

/** Home: every tool on one screen. The two most likely ones get big tiles, the rest a compact grid. */
@Composable
private fun HomeScreen(order: List<Tool>, open: (Tool) -> Unit) {
    LazyVerticalGrid(GridCells.Fixed(2), contentPadding = PaddingValues(16.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item(span = { GridItemSpan(maxLineSpan) }) {
            Text("What do you want to print?", style = MaterialTheme.typography.titleMedium)
        }
        items(order.take(2), key = { it.key }) { t ->
            Card(onClick = { open(t) }, colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer),
                modifier = Modifier.height(148.dp)) {
                Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.SpaceBetween) {
                    Box(Modifier.size(48.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary), contentAlignment = Alignment.Center) {
                        Icon(t.icon, null, tint = MaterialTheme.colorScheme.onPrimary)
                    }
                    Column {
                        Text(t.label, style = MaterialTheme.typography.titleLarge)
                        Text(t.blurb, style = MaterialTheme.typography.bodySmall, maxLines = 2)
                    }
                }
            }
        }
        item(span = { GridItemSpan(maxLineSpan) }) {
            Text("More tools", style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(top = 8.dp))
        }
        items(order.drop(2), key = { it.key }) { t ->
            Card(onClick = { open(t) }, colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerHigh)) {
                Row(Modifier.fillMaxWidth().heightIn(min = 72.dp).padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(t.icon, null, tint = MaterialTheme.colorScheme.primary)
                    Column(Modifier.padding(start = 12.dp)) {
                        Text(t.label, style = MaterialTheme.typography.titleSmall, maxLines = 1)
                        Text(t.blurb, style = MaterialTheme.typography.bodySmall, maxLines = 2,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}

@Composable
private fun QueueScreen(queue: List<QueueEntry>) {
    val now = rememberNow()
    val active = queue.filter { it.active }
    val done = queue.filterNot { it.active }.reversed()
    if (queue.isEmpty()) {
        Column(Modifier.fillMaxSize().padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            Icon(Icons.Default.Print, null, Modifier.size(48.dp), tint = MaterialTheme.colorScheme.outline)
            Text("Nothing in the queue", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 12.dp))
            Text("Prints show up here with the time they have left.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        return
    }
    LazyColumn(Modifier.fillMaxSize()) {
        if (active.isNotEmpty()) item {
            Text("All done in about ${eta(active.sumOf { it.remaining(now) })}", style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(16.dp, 12.dp))
        }
        var ahead = 0.0
        items(active, key = { it.id }) { e ->
            val startsIn = ahead
            ahead += e.remaining(now)
            ListItem(
                leadingContent = { Thumb(e.thumb) },
                headlineContent = { Text(e.title, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                supportingContent = {
                    Column {
                        Text(when (e.state) {
                            JobState.WAITING -> "Starts in about ${eta(startsIn)} · takes ${eta(e.seconds)}"
                            JobState.CONNECTING -> "Connecting… ${left(e, now)}"
                            else -> "${stateText(e, now)} · ${left(e, now)}"
                        })
                        if (e.state != JobState.WAITING) LinearProgressIndicator({ e.timeFraction(now) }, Modifier.fillMaxWidth().padding(top = 6.dp))
                    }
                },
                trailingContent = {
                    if (e.state == JobState.WAITING) IconButton({ Printers.cancel(e.id) }) { Icon(Icons.Default.Close, "Remove from queue") }
                },
            )
        }
        if (done.isNotEmpty()) item {
            Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Finished", style = MaterialTheme.typography.labelLarge, modifier = Modifier.weight(1f))
                TextButton({ Printers.clearFinished() }) { Text("Clear") }
            }
        }
        items(done, key = { it.id }) { e ->
            val time = DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(e.finishedAt))
            ListItem(
                leadingContent = { Thumb(e.thumb) },
                headlineContent = { Text(e.title, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                supportingContent = {
                    Text(when (e.state) {
                        JobState.DONE -> "Printed at $time"
                        JobState.CANCELLED -> "Removed at $time"
                        else -> "Failed: ${e.error}"
                    }, color = if (e.state == JobState.FAILED) MaterialTheme.colorScheme.error else Color.Unspecified)
                },
                trailingContent = {
                    Icon(when (e.state) { JobState.DONE -> Icons.Default.CheckCircle; JobState.FAILED -> Icons.Default.Error; else -> Icons.Default.RemoveCircleOutline }, null,
                        tint = if (e.state == JobState.FAILED) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary)
                },
            )
        }
    }
}

@Composable
private fun Thumb(bmp: Bitmap?) {
    val img = remember(bmp) { bmp?.asImageBitmap() }
    Box(Modifier.size(48.dp).background(Color.White).border(1.dp, Color(0xFFDDDDDD)), contentAlignment = Alignment.TopCenter) {
        img?.let { Image(it, null, Modifier.fillMaxWidth(), contentScale = ContentScale.FillWidth, alignment = Alignment.TopCenter) }
    }
}

/** Paper-like preview of exactly what will print. */
@Composable
private fun Preview(bmp: Bitmap?, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().background(Color(0xFFE6E6E1)).padding(12.dp), contentAlignment = Alignment.TopCenter) {
        if (bmp == null) Text("Nothing to print yet", color = Color.Gray, modifier = Modifier.padding(32.dp))
        else Image(bmp.asImageBitmap(), null, Modifier.widthIn(max = 384.dp).fillMaxWidth().background(Color.White)
            .border(1.dp, Color(0xFFCCCCCC)), contentScale = ContentScale.FillWidth, filterQuality = FilterQuality.None)
    }
}

/** Renders [source] to rows off the main thread whenever its inputs change. */
@Composable
private fun rememberRows(vararg keys: Any?, source: suspend (Int) -> List<ByteArray>?): List<ByteArray>? {
    var rows by remember { mutableStateOf<List<ByteArray>?>(null) }
    LaunchedEffect(*keys) { rows = withContext(Dispatchers.Default) { source(Printers.width) } }
    return rows
}

/** Copies, time estimate and the Print button (the start point of the flying slip). */
@Composable
private fun PrintBar(lines: Int?, onPrint: (copies: Int) -> Unit) {
    val fly = LocalFly.current
    var copies by remember { mutableIntStateOf(1) }
    Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
        IconButton({ if (copies > 1) copies-- }) { Icon(Icons.Default.Remove, "fewer") }
        Text("×$copies")
        IconButton({ copies++ }) { Icon(Icons.Default.Add, "more") }
        if (lines != null) Text("about ${eta(Printers.estimate(lines, copies))}", style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.weight(1f))
        Button({ onPrint(copies) }, enabled = lines != null,
            modifier = Modifier.onGloballyPositioned { fly.from = it.boundsInRoot().center }) {
            Icon(Icons.Default.Print, null); Spacer(Modifier.width(8.dp)); Text("Print")
        }
    }
}

private fun textRows(bmp: Bitmap, width: Int): List<ByteArray> {
    val (g, h) = Imaging.toGray(bmp, width, autoRotate = false)
    return Imaging.rows(g, width, h, Dither.THRESHOLD)
}

/** Photo (dithered, wide pictures turned to fit) or Document (PDF pages, sharp, never rotated). */
@Composable
private fun ImageTab(document: Boolean, pages: List<Bitmap>, setPages: (List<Bitmap>) -> Unit, print: (Job) -> Unit) {
    val ctx = LocalContext.current
    var error by remember { mutableStateOf<String?>(null) }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let {
            Thread {
                runCatching {
                    when (val l = Sources.load(ctx, it, Printers.width)) {
                        is Sources.Loaded.Pages -> l.bitmaps
                        is Sources.Loaded.Text -> listOf(Imaging.textBitmap(l.text, Printers.width, 24f))
                    }
                }.onSuccess { b -> error = null; setPages(b) }.onFailure { e -> error = "Can't open it: ${e.message}" }
            }.start()
        }
    }
    var dither by remember(document) { mutableStateOf(if (document) Dither.THRESHOLD else Dither.FLOYD) }
    var bright by remember { mutableFloatStateOf(0f) }
    var contrast by remember { mutableFloatStateOf(1f) }
    val rows = rememberRows(pages, dither, bright, contrast) { w ->
        pages.takeIf { it.isNotEmpty() }?.flatMap {
            val (g, h) = Imaging.toGray(it, w, autoRotate = !document, brightness = bright, contrast = contrast)
            Imaging.rows(g, w, h, dither)
        }
    }
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
            Row(Modifier.padding(16.dp, 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                if (document) OutlinedButton({ pick.launch(arrayOf("application/pdf", "text/plain", "image/*")) }) { Text("Choose PDF or file") }
                else OutlinedButton({ pick.launch(arrayOf("image/*")) }) { Text("Choose photo") }
                if (document && pages.isNotEmpty()) Text("${pages.size} page" + if (pages.size > 1) "s" else "", style = MaterialTheme.typography.bodySmall)
            }
            error?.let { Text(it, Modifier.padding(horizontal = 16.dp), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            Row(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Dither.entries.forEach { FilterChip(dither == it, { dither = it }, { Text(it.label) }) }
            }
            if (!document) {
                LabeledSlider("Brightness", bright, -0.5f..0.5f) { bright = it }
                LabeledSlider("Contrast", contrast, 0.5f..2f) { contrast = it }
            }
            Preview(rows?.let { Imaging.preview(it, Printers.width) })
        }
        val title = if (document) "Document" + if (pages.size > 1) " (${pages.size} pages)" else "" else "Photo"
        PrintBar(rows?.size) { n -> rows?.let { print(Job(title, it, Printers.width, copies = n)) } }
    }
}

@Composable
private fun LabeledSlider(label: String, v: Float, range: ClosedFloatingPointRange<Float>, set: (Float) -> Unit) {
    Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.width(90.dp), style = MaterialTheme.typography.bodySmall)
        Slider(v, set, valueRange = range, modifier = Modifier.weight(1f))
    }
}

@Composable
private fun TextTab(text: String, setText: (String) -> Unit, print: (Job) -> Unit) {
    var size by remember { mutableFloatStateOf(28f) }
    var bold by remember { mutableStateOf(false) }
    val rows = rememberRows(text, size, bold) { w -> text.takeIf { it.isNotBlank() }?.let { textRows(Imaging.textBitmap(it, w, size, bold), w) } }
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
            OutlinedTextField(text, setText, Modifier.fillMaxWidth().padding(16.dp), label = { Text("Note") }, minLines = 3)
            Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                FilterChip(bold, { bold = !bold }, { Text("Bold") })
                Slider(size, { size = it }, valueRange = 18f..72f, modifier = Modifier.weight(1f).padding(start = 12.dp))
            }
            Preview(rows?.let { Imaging.preview(it, Printers.width) })
        }
        PrintBar(rows?.size) { n -> rows?.let { print(Job(text.lineSequence().first(), it, Printers.width, Protocol.MODE_TEXT, n)) } }
    }
}

@Composable
private fun ListTab(print: (Job) -> Unit) {
    var title by remember { mutableStateOf("To do") }
    var items by remember { mutableStateOf("") }
    val rows = rememberRows(title, items) { w ->
        items.lines().filter { it.isNotBlank() }.takeIf { it.isNotEmpty() }?.let { textRows(Imaging.checklistBitmap(title, it, w), w) }
    }
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
            OutlinedTextField(title, { title = it }, Modifier.fillMaxWidth().padding(16.dp, 8.dp), label = { Text("Title") }, singleLine = true)
            OutlinedTextField(items, { items = it }, Modifier.fillMaxWidth().padding(16.dp, 8.dp), label = { Text("One item per line") }, minLines = 4)
            Preview(rows?.let { Imaging.preview(it, Printers.width) })
        }
        PrintBar(rows?.size) { n -> rows?.let { print(Job(title, it, Printers.width, Protocol.MODE_TEXT, n)) } }
    }
}

@Composable
private fun BannerTab(print: (Job) -> Unit) {
    var text by remember { mutableStateOf("") }
    val rows = rememberRows(text) { w -> text.takeIf { it.isNotBlank() }?.let { textRows(Imaging.bannerBitmap(it, w), w) } }
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
            OutlinedTextField(text, { text = it }, Modifier.fillMaxWidth().padding(16.dp), label = { Text("Banner text") }, singleLine = true)
            Preview(rows?.let { Imaging.preview(it, Printers.width) }, Modifier.heightIn(max = 600.dp))
        }
        PrintBar(rows?.size) { n -> rows?.let { print(Job("banner $text", it, Printers.width, Protocol.MODE_TEXT, n)) } }
    }
}

@Composable
private fun CodeTab(print: (Job) -> Unit) {
    var content by remember { mutableStateOf("") }
    var caption by remember { mutableStateOf("") }
    var format by remember { mutableStateOf(BarcodeFormat.QR_CODE) }
    val formats = listOf(BarcodeFormat.QR_CODE to "QR", BarcodeFormat.CODE_128 to "Barcode")
    val rows = rememberRows(content, caption, format) { w ->
        if (content.isBlank()) null else runCatching {
            val code = textRows(Imaging.codeBitmap(content, format, w), w)
            code + if (caption.isBlank()) emptyList() else textRows(Imaging.textBitmap(caption, w), w)
        }.getOrNull()
    }
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
            Row(Modifier.padding(16.dp, 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                formats.forEach { (f, l) -> FilterChip(format == f, { format = f }, { Text(l) }) }
            }
            OutlinedTextField(content, { content = it }, Modifier.fillMaxWidth().padding(16.dp, 4.dp), label = { Text("Link or text") })
            OutlinedTextField(caption, { caption = it }, Modifier.fillMaxWidth().padding(16.dp, 4.dp), label = { Text("Caption (optional)") })
            Preview(rows?.let { Imaging.preview(it, Printers.width) })
        }
        PrintBar(rows?.size) { n -> rows?.let { print(Job("code", it, Printers.width, copies = n)) } }
    }
}

/** One product row in the receipt editor, as typed. */
private data class ItemRow(val name: String = "", val qty: String = "1", val price: String = "")

@Composable
private fun ReceiptTab(print: (Job) -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val prefs = remember { ctx.getSharedPreferences("receipt", Context.MODE_PRIVATE) }
    var business by remember { mutableStateOf(prefs.getString("business", "").orEmpty()) }
    var address by remember { mutableStateOf(prefs.getString("address", "").orEmpty()) }
    var url by remember { mutableStateOf(prefs.getString("url", "").orEmpty()) }
    var footer by remember { mutableStateOf(prefs.getString("footer", DEFAULT_FOOTER) ?: DEFAULT_FOOTER) }
    var showBusiness by remember { mutableStateOf(business.isBlank()) }
    val items = remember {
        mutableStateListOf<ItemRow>().apply {
            runCatching {
                val a = JSONArray(prefs.getString("items", "[]"))
                for (i in 0 until a.length()) a.getJSONArray(i).let { add(ItemRow(it.getString(0), it.getString(1), it.getString(2))) }
            }
            if (isEmpty()) add(ItemRow())
        }
    }
    val list = items.toList()
    fun build() = Receipt.fromRows(business, address, url, footer, list.map { Triple(it.name, it.qty, it.price) })
    val built = remember(business, address, url, footer, list) { runCatching { build() } }

    LaunchedEffect(business, address, url, footer, list) {
        val a = JSONArray()
        list.forEach { a.put(JSONArray(listOf(it.name, it.qty, it.price))) }
        prefs.edit().putString("business", business).putString("address", address).putString("url", url)
            .putString("footer", footer).putString("items", a.toString()).apply()
    }
    val rows = rememberRows(built) { w -> built.getOrNull()?.let { textRows(ReceiptArt.bitmap(it, w), w) } }

    Column(Modifier.fillMaxSize()) {
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
            TextButton({ showBusiness = !showBusiness }, Modifier.padding(horizontal = 8.dp)) {
                Text(if (business.isBlank()) "Business details" else business, Modifier.weight(1f, fill = false))
                Icon(if (showBusiness) Icons.Default.ExpandLess else Icons.Default.ExpandMore, null)
            }
            if (showBusiness) {
                OutlinedTextField(business, { business = it }, Modifier.fillMaxWidth().padding(16.dp, 2.dp), label = { Text("Business name") }, singleLine = true)
                OutlinedTextField(address, { address = it }, Modifier.fillMaxWidth().padding(16.dp, 2.dp), label = { Text("Address") }, singleLine = true)
                OutlinedTextField(url, { url = it }, Modifier.fillMaxWidth().padding(16.dp, 2.dp), label = { Text("Website") }, singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
                OutlinedTextField(footer, { footer = it }, Modifier.fillMaxWidth().padding(16.dp, 2.dp), label = { Text("Message at the bottom") }, singleLine = true)
            }
            Text("Products", Modifier.padding(16.dp, 8.dp, 16.dp, 0.dp), style = MaterialTheme.typography.labelLarge)
            items.forEachIndexed { i, it ->
                Column(Modifier.padding(16.dp, 4.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        OutlinedTextField(it.name, { v -> items[i] = it.copy(name = v) }, Modifier.weight(1f),
                            label = { Text("Product ${i + 1}") }, singleLine = true)
                        IconButton({ items.removeAt(i); if (items.isEmpty()) items.add(ItemRow()) }) { Icon(Icons.Default.Close, "remove") }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(end = 48.dp)) {
                        OutlinedTextField(it.qty, { v -> items[i] = it.copy(qty = v) }, Modifier.weight(1f), label = { Text("Qty") },
                            singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal))
                        OutlinedTextField(it.price, { v -> items[i] = it.copy(price = v) }, Modifier.weight(2f), label = { Text("Price (CLP)") },
                            prefix = { Text("$") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                    }
                }
            }
            Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                TextButton({ items.add(ItemRow()) }) { Icon(Icons.Default.Add, null); Spacer(Modifier.width(4.dp)); Text("Add product") }
                Spacer(Modifier.weight(1f))
                built.getOrNull()?.let {
                    Text("Total ${Clp.format(it.total)}", Modifier.padding(end = 8.dp), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                }
            }
            built.exceptionOrNull()?.let {
                Text(it.message ?: "Can't make this receipt", Modifier.padding(16.dp, 0.dp), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            }
            Preview(rows?.let { Imaging.preview(it, Printers.width) })
        }
        PrintBar(rows?.size) { n ->
            // Rebuilt at print time so the date, time and receipt number are the moment it prints.
            scope.launch {
                val job = withContext(Dispatchers.Default) {
                    runCatching { build() }.getOrNull()?.let {
                        Job("Receipt ${Clp.format(it.total)}", textRows(ReceiptArt.bitmap(it, Printers.width), Printers.width), Printers.width, Protocol.MODE_TEXT, n)
                    }
                }
                job?.let(print)
            }
        }
    }
}

@Composable
private fun HistoryTab(reprint: (HistoryItem) -> Unit) {
    val items by Printers.history.collectAsState()
    val fly = LocalFly.current
    if (items.isEmpty()) Text("Prints show up here so you can reprint them.", Modifier.padding(24.dp), color = Color.Gray)
    LazyColumn(Modifier.fillMaxSize()) {
        items(items, key = { it.file.name }) { item ->
            val thumb = remember(item.file) { BitmapFactory.decodeFile(item.file.path)?.asImageBitmap() }
            var at by remember { mutableStateOf(Offset.Unspecified) }
            ListItem(
                leadingContent = { thumb?.let { Image(it, null, Modifier.size(56.dp).background(Color.White), contentScale = ContentScale.Fit) } },
                headlineContent = { Text(item.title, maxLines = 1) },
                supportingContent = { Text(DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date(item.time))) },
                trailingContent = {
                    Row {
                        IconButton({ fly.from = at; reprint(item) }, Modifier.onGloballyPositioned { at = it.boundsInRoot().center }) {
                            Icon(Icons.Default.Print, "reprint")
                        }
                        IconButton({ Printers.deleteHistory(item) }) { Icon(Icons.Default.Delete, "delete") }
                    }
                },
            )
        }
    }
}

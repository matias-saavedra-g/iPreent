package com.ipreent

import android.Manifest
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.google.zxing.BarcodeFormat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.DateFormat
import java.util.Date

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

private enum class Tab(val label: String, val icon: androidx.compose.ui.graphics.vector.ImageVector) {
    PHOTO("Photo", Icons.Default.Image), TEXT("Text", Icons.Default.TextFields), LIST("List", Icons.Default.Checklist),
    BANNER("Banner", Icons.Default.ViewDay), CODE("QR", Icons.Default.QrCode2), HISTORY("History", Icons.Default.History),
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun App(shared: MutableState<Sources.Loaded?>) {
    var tab by remember { mutableStateOf(Tab.PHOTO) }
    var photo by remember { mutableStateOf<List<Bitmap>>(emptyList()) }
    var text by remember { mutableStateOf("") }
    val snack = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    var granted by remember { mutableStateOf(false) }
    val askPerms = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { r ->
        granted = r.values.all { it }
    }
    LaunchedEffect(Unit) { askPerms.launch(PERMS) }

    shared.value?.let { s ->
        when (s) {
            is Sources.Loaded.Pages -> { photo = s.bitmaps; tab = Tab.PHOTO }
            is Sources.Loaded.Text -> { text = s.text; tab = Tab.TEXT }
        }
        shared.value = null
    }

    val print: (Job) -> Unit = { job ->
        if (!granted) askPerms.launch(PERMS)
        else scope.launch {
            try { Printers.enqueue(job).await(); snack.showSnackbar("Printed") }
            catch (e: Throwable) { snack.showSnackbar(e.message ?: "Print failed") }
        }
    }

    Scaffold(
        topBar = { TopAppBar(title = { Text("iPreent", fontWeight = FontWeight.Bold) }, actions = { PrinterChip(granted, snack) }) },
        bottomBar = {
            NavigationBar {
                Tab.entries.forEach {
                    NavigationBarItem(selected = tab == it, onClick = { tab = it },
                        icon = { Icon(it.icon, null) }, label = { Text(it.label, maxLines = 1) })
                }
            }
        },
        snackbarHost = { SnackbarHost(snack) },
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            StatusLine()
            Box(Modifier.weight(1f)) {
                when (tab) {
                    Tab.PHOTO -> PhotoTab(photo, { photo = it }, print)
                    Tab.TEXT -> TextTab(text, { text = it }, print)
                    Tab.LIST -> ListTab(print)
                    Tab.BANNER -> BannerTab(print)
                    Tab.CODE -> CodeTab(print)
                    Tab.HISTORY -> HistoryTab(snack)
                }
            }
        }
    }
}

@Composable
private fun PrinterChip(granted: Boolean, snack: SnackbarHostState) {
    val scope = rememberCoroutineScope()
    var menu by remember { mutableStateOf(false) }
    var found by remember { mutableStateOf<List<Found>?>(null) }
    val darkness by Printers.darkness.collectAsState()
    Box {
        AssistChip(onClick = { menu = true }, label = { Text(Printers.savedName ?: "No printer") },
            leadingIcon = { Icon(Icons.Default.Print, null, Modifier.size(18.dp)) })
        DropdownMenu(menu, { menu = false }) {
            Text("Darkness", Modifier.padding(horizontal = 12.dp), style = MaterialTheme.typography.labelMedium)
            Darkness.entries.forEach { d ->
                DropdownMenuItem(text = { Text("${d.label} (${d.energy})") }, onClick = { Printers.setDarkness(d) },
                    leadingIcon = { RadioButton(darkness == d, null) })
            }
            HorizontalDivider()
            DropdownMenuItem(text = { Text("Status / battery") }, enabled = granted, onClick = {
                menu = false
                scope.launch { snack.showSnackbar(runCatching { Printers.readStatus() }.getOrElse { it.message ?: "error" }) }
            })
            DropdownMenuItem(text = { Text("Find printers") }, enabled = granted, onClick = {
                menu = false
                scope.launch { found = runCatching { Printers.scan() }.getOrElse { snack.showSnackbar(it.message ?: "Scan failed"); null } }
            })
            DropdownMenuItem(text = { Text("Forget printer") }, onClick = { menu = false; Printers.forget() })
        }
    }
    found?.let { list ->
        AlertDialog(onDismissRequest = { found = null }, confirmButton = { TextButton({ found = null }) { Text("Close") } },
            title = { Text(if (list.isEmpty()) "No printers found" else "Pick a printer") },
            text = {
                Column {
                    list.forEach { f ->
                        TextButton({ Printers.remember(f); found = null }) { Text("${f.name}  ·  ${f.address}") }
                    }
                }
            })
    }
}

@Composable
private fun StatusLine() {
    val status by Printers.status.collectAsState()
    val progress by Printers.progress.collectAsState()
    val queued by Printers.queued.collectAsState()
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)) {
        Text(status + if (queued > 1) "  ·  ${queued - 1} waiting" else "", style = MaterialTheme.typography.bodySmall)
        progress?.let { LinearProgressIndicator({ it }, Modifier.fillMaxWidth().padding(top = 4.dp)) }
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

@Composable
private fun PrintBar(enabled: Boolean, onPrint: (copies: Int) -> Unit) {
    var copies by remember { mutableIntStateOf(1) }
    Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
        IconButton({ if (copies > 1) copies-- }) { Icon(Icons.Default.Remove, "fewer") }
        Text("×$copies")
        IconButton({ copies++ }) { Icon(Icons.Default.Add, "more") }
        Spacer(Modifier.weight(1f))
        Button({ onPrint(copies) }, enabled = enabled) { Icon(Icons.Default.Print, null); Spacer(Modifier.width(8.dp)); Text("Print") }
    }
}

private fun textRows(bmp: Bitmap, width: Int): List<ByteArray> {
    val (g, h) = Imaging.toGray(bmp, width, autoRotate = false)
    return Imaging.rows(g, width, h, Dither.THRESHOLD)
}

@Composable
private fun PhotoTab(pages: List<Bitmap>, setPages: (List<Bitmap>) -> Unit, print: (Job) -> Unit) {
    val ctx = LocalContext.current
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri?.let { Thread { (Sources.load(ctx, it, Printers.width) as? Sources.Loaded.Pages)?.let { p -> setPages(p.bitmaps) } }.start() }
    }
    var dither by remember { mutableStateOf(Dither.FLOYD) }
    var bright by remember { mutableFloatStateOf(0f) }
    var contrast by remember { mutableFloatStateOf(1f) }
    val rows = rememberRows(pages, dither, bright, contrast) { w ->
        pages.takeIf { it.isNotEmpty() }?.flatMap {
            val (g, h) = Imaging.toGray(it, w, brightness = bright, contrast = contrast)
            Imaging.rows(g, w, h, dither)
        }
    }
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
            Row(Modifier.padding(16.dp, 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton({ pick.launch(arrayOf("image/*", "application/pdf")) }) { Text("Choose photo or PDF") }
            }
            Row(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Dither.entries.forEach { FilterChip(dither == it, { dither = it }, { Text(it.label) }) }
            }
            LabeledSlider("Brightness", bright, -0.5f..0.5f) { bright = it }
            LabeledSlider("Contrast", contrast, 0.5f..2f) { contrast = it }
            Preview(rows?.let { Imaging.preview(it, Printers.width) })
        }
        PrintBar(rows != null) { n -> rows?.let { print(Job("photo", it, Printers.width, copies = n)) } }
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
        PrintBar(rows != null) { n -> rows?.let { print(Job(text.lineSequence().first(), it, Printers.width, Protocol.MODE_TEXT, n)) } }
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
        PrintBar(rows != null) { n -> rows?.let { print(Job(title, it, Printers.width, Protocol.MODE_TEXT, n)) } }
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
        PrintBar(rows != null) { n -> rows?.let { print(Job("banner $text", it, Printers.width, Protocol.MODE_TEXT, n)) } }
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
        PrintBar(rows != null) { n -> rows?.let { print(Job("code", it, Printers.width, copies = n)) } }
    }
}

@Composable
private fun HistoryTab(snack: SnackbarHostState) {
    val items by Printers.history.collectAsState()
    val scope = rememberCoroutineScope()
    if (items.isEmpty()) Text("Prints show up here so you can reprint them.", Modifier.padding(24.dp), color = Color.Gray)
    LazyColumn(Modifier.fillMaxSize()) {
        items(items, key = { it.file.name }) { item ->
            val thumb = remember(item.file) { BitmapFactory.decodeFile(item.file.path)?.asImageBitmap() }
            ListItem(
                leadingContent = { thumb?.let { Image(it, null, Modifier.size(56.dp).background(Color.White), contentScale = ContentScale.Fit) } },
                headlineContent = { Text(item.title, maxLines = 1) },
                supportingContent = { Text(DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date(item.time))) },
                trailingContent = {
                    Row {
                        IconButton({ scope.launch { runCatching { Printers.reprint(item).await() }.onFailure { snack.showSnackbar(it.message ?: "Failed") } } }) {
                            Icon(Icons.Default.Print, "reprint")
                        }
                        IconButton({ Printers.deleteHistory(item) }) { Icon(Icons.Default.Delete, "delete") }
                    }
                },
            )
        }
    }
}

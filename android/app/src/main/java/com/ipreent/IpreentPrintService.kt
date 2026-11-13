package com.ipreent

import android.os.ParcelFileDescriptor
import android.print.PrintAttributes
import android.print.PrinterCapabilitiesInfo
import android.print.PrinterId
import android.print.PrinterInfo
import android.printservice.PrintJob
import android.printservice.PrintService
import android.printservice.PrinterDiscoverySession
import kotlinx.coroutines.*

/** Android print service: "Print" from Chrome, Files, Gallery or Docs shows iPreent as a printer. */
class IpreentPrintService : PrintService() {
    private val scope = MainScope()

    override fun onCreate() { super.onCreate(); Printers.init(this) }
    override fun onDestroy() { scope.cancel(); super.onDestroy() }

    override fun onCreatePrinterDiscoverySession() = object : PrinterDiscoverySession() {
        override fun onStartPrinterDiscovery(priorityList: MutableList<PrinterId>) {
            val id = generatePrinterId("ipreent")
            val name = Printers.savedName ?: Lang.str(this@IpreentPrintService, R.string.print_service_name)
            // Paper is a continuous roll; offer a long page at the roll width (58 mm ≈ 2.28 in).
            val roll = PrintAttributes.MediaSize("roll58", Lang.str(this@IpreentPrintService, R.string.print_service_roll), 2283, 11690)
            val dpi = Printers.model().dpi
            val caps = PrinterCapabilitiesInfo.Builder(id)
                .addMediaSize(roll, true)
                .addMediaSize(PrintAttributes.MediaSize.ISO_A6, false)
                .addResolution(PrintAttributes.Resolution("r", "$dpi dpi", dpi, dpi), true)
                .setColorModes(PrintAttributes.COLOR_MODE_MONOCHROME, PrintAttributes.COLOR_MODE_MONOCHROME)
                .setMinMargins(PrintAttributes.Margins.NO_MARGINS)
                .build()
            addPrinters(listOf(PrinterInfo.Builder(id, name, PrinterInfo.STATUS_IDLE).setCapabilities(caps).build()))
        }
        override fun onStopPrinterDiscovery() {}
        override fun onValidatePrinters(printerIds: MutableList<PrinterId>) {}
        override fun onStartPrinterStateTracking(printerId: PrinterId) {}
        override fun onStopPrinterStateTracking(printerId: PrinterId) {}
        override fun onDestroy() {}
    }

    override fun onPrintJobQueued(job: PrintJob) {
        job.start()
        scope.launch {
            try {
                val width = Printers.width
                val data = job.document.data ?: fail(R.string.err_no_document, "no document")
                // The spooler hands us a pipe; PdfRenderer needs a seekable file, so copy it first.
                val pages = withContext(Dispatchers.IO) {
                    val tmp = java.io.File.createTempFile("job", ".pdf", cacheDir)
                    try {
                        ParcelFileDescriptor.AutoCloseInputStream(data).use { i -> tmp.outputStream().use { i.copyTo(it) } }
                        ParcelFileDescriptor.open(tmp, ParcelFileDescriptor.MODE_READ_ONLY).use { Sources.pdfPages(it, width) }
                    } finally { tmp.delete() }
                }
                val rows = withContext(Dispatchers.Default) {
                    pages.flatMap { b ->
                        val (g, h) = Imaging.toGray(b, width, autoRotate = false)
                        Imaging.rows(trimBlank(g, width, h), width, trimmedHeight(g, width, h), Dither.FLOYD)
                    }
                }
                Printers.enqueue(Job(job.document.info.name, rows, width)).await()
                job.complete()
            } catch (e: Throwable) {
                job.fail(Lang.text(this@IpreentPrintService, e))
            }
        }
    }

    override fun onRequestCancelPrintJob(job: PrintJob) { job.cancel() }

    // Documents printed on a tall "roll" page end in white space; don't print metres of nothing.
    private fun trimmedHeight(g: FloatArray, w: Int, h: Int): Int {
        var last = h - 1
        while (last > 0 && (0 until w).all { g[last * w + it] > 240f }) last--
        return last + 1
    }
    private fun trimBlank(g: FloatArray, w: Int, h: Int) = g.copyOf(trimmedHeight(g, w, h) * w)
}

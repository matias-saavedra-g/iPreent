package com.ipreent

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ImageDecoder
import android.graphics.pdf.PdfRenderer
import android.net.Uri
import android.os.Build
import android.os.ParcelFileDescriptor
import android.provider.MediaStore

/** Load what the user shared or picked into bitmaps at the paper width. Port of ipreent/convert.py. */
object Sources {
    fun pdfPages(fd: ParcelFileDescriptor, width: Int, pages: Set<Int>? = null): List<Bitmap> =
        PdfRenderer(fd).use { r ->
            (0 until r.pageCount).filter { pages == null || it in pages }.map { i ->
                r.openPage(i).use { page ->
                    val h = page.height * width / page.width
                    Bitmap.createBitmap(width, h, Bitmap.Config.ARGB_8888).also {
                        Canvas(it).drawColor(Color.WHITE)
                        page.render(it, null, null, PdfRenderer.Page.RENDER_MODE_FOR_PRINT)
                    }
                }
            }
        }

    fun image(ctx: Context, uri: Uri): Bitmap =
        if (Build.VERSION.SDK_INT >= 28)
            ImageDecoder.decodeBitmap(ImageDecoder.createSource(ctx.contentResolver, uri)) { d, info, _ ->
                d.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
                val big = maxOf(info.size.width, info.size.height)
                if (big > 3000) d.setTargetSampleSize(big / 1500)   // phone photos: no need for 12 MP
            }
        else @Suppress("DEPRECATION") MediaStore.Images.Media.getBitmap(ctx.contentResolver, uri)

    /** Images and PDFs become bitmaps; text files become text. */
    fun load(ctx: Context, uri: Uri, width: Int): Loaded {
        val type = ctx.contentResolver.getType(uri).orEmpty()
        return when {
            type == "application/pdf" || uri.path.orEmpty().endsWith(".pdf", true) ->
                Loaded.Pages(ctx.contentResolver.openFileDescriptor(uri, "r")!!.use { pdfPages(it, width) })
            type.startsWith("text/") ->
                Loaded.Text(ctx.contentResolver.openInputStream(uri)!!.bufferedReader().readText())
            else -> Loaded.Pages(listOf(image(ctx, uri)))
        }
    }

    sealed interface Loaded {
        data class Pages(val bitmaps: List<Bitmap>) : Loaded
        data class Text(val text: String) : Loaded
    }
}

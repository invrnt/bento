package dev.bento.feature.recovery

import android.content.Context
import android.os.Bundle
import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.print.PageRange
import android.print.PrintAttributes
import android.print.PrintDocumentAdapter
import android.print.PrintDocumentInfo
import android.print.PrintManager
import java.io.FileOutputStream

/** `Imprimir`: hands the same one-page kit document to the system print service. */
object RecoveryKitPrint {
    fun print(context: Context, jobName: String, document: RecoveryKitDocument): Boolean {
        val manager = context.getSystemService(PrintManager::class.java) ?: return false
        val attributes = PrintAttributes.Builder()
            .setMediaSize(PrintAttributes.MediaSize.ISO_A4)
            .setColorMode(PrintAttributes.COLOR_MODE_MONOCHROME)
            .build()
        return runCatching { manager.print(jobName, Adapter(context.applicationContext, jobName, document), attributes) }.isSuccess
    }

    private class Adapter(private val context: Context, private val name: String, private val document: RecoveryKitDocument) :
        PrintDocumentAdapter() {
        override fun onLayout(
            oldAttributes: PrintAttributes?,
            newAttributes: PrintAttributes,
            cancellationSignal: CancellationSignal,
            callback: LayoutResultCallback,
            extras: Bundle?
        ) {
            if (cancellationSignal.isCanceled) {
                callback.onLayoutCancelled()
                return
            }
            val info = PrintDocumentInfo.Builder("$name.pdf")
                .setContentType(PrintDocumentInfo.CONTENT_TYPE_DOCUMENT)
                .setPageCount(1)
                .build()
            callback.onLayoutFinished(info, oldAttributes != newAttributes)
        }

        override fun onWrite(
            pages: Array<out PageRange>,
            destination: ParcelFileDescriptor,
            cancellationSignal: CancellationSignal,
            callback: WriteResultCallback
        ) {
            val written = runCatching {
                FileOutputStream(destination.fileDescriptor).use { RecoveryKitPdf.write(context, document, it) }
            }
            if (written.isSuccess) callback.onWriteFinished(arrayOf(PageRange.ALL_PAGES)) else callback.onWriteFailed(null)
        }
    }
}

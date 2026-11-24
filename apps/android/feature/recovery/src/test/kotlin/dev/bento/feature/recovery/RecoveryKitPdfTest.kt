package dev.bento.feature.recovery

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import androidx.test.core.app.ApplicationProvider
import dev.bento.designsystem.component.QrMatrix
import dev.bento.testing.TrustFixtures
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/**
 * The printed kit layout draws on an A4-sized canvas (PdfDocument itself is native: the real PDF is written in the
 * instrumented RecoveryKitPdfInstrumentedTest).
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "es")
class RecoveryKitPdfTest {
    @Test
    fun drawsTheKitOnAWhitePage() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val bitmap = Bitmap.createBitmap(RecoveryKitPdf.PAGE_WIDTH, RecoveryKitPdf.PAGE_HEIGHT, Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(Color.WHITE)
        val document =
            RecoveryKitDocument(
                TrustFixtures.RECOVERY_CODE,
                QrMatrix.fromRows(listOf("101", "010", "101")),
                "Ana",
                "2026-11-24T10:00:00+00:00"
            )
        RecoveryKitPdf.draw(context, Canvas(bitmap), document)
        var inked = 0
        for (y in 0 until bitmap.height step 4) for (x in 0 until bitmap.width step 4) if (bitmap.getPixel(x, y) != Color.WHITE) inked++
        assertTrue("the page has the header, code box, QR and copy ($inked inked samples)", inked > 500)
    }
}

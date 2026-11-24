package dev.bento.feature.recovery

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import androidx.compose.ui.graphics.toArgb
import androidx.core.content.res.ResourcesCompat
import dev.bento.designsystem.R as DesignR
import dev.bento.designsystem.component.QrMatrix
import dev.bento.designsystem.generated.BentoTokens
import dev.bento.strings.R as StringsR
import java.io.OutputStream
import java.time.Instant
import java.util.Locale

/** What the printed kit shows; the code never leaves memory except into the document the person saves or prints. */
data class RecoveryKitDocument(
    val code: String,
    val qr: QrMatrix?,
    val accountName: String?,
    val vaultCreatedAt: String?,
    val printedAt: Instant = Instant.now()
)

/**
 * The "Kit de recuperación de Bento" page as an A4 [PdfDocument], with the same content as the desktop kit
 * (apps/web `RecoveryKitSheet`): brand header, account, dates, the 9 groups with the `bento-recovery:` QR, how to
 * use it and the warning. Always light colors (it is paper). Used by `Guardar PDF` and `Imprimir`.
 */
object RecoveryKitPdf {
    const val PAGE_WIDTH = 595 // A4 in PostScript points
    const val PAGE_HEIGHT = 842
    private const val MARGIN = 51f // 18 mm

    fun write(context: Context, document: RecoveryKitDocument, output: OutputStream) {
        val pdf = PdfDocument()
        try {
            val page = pdf.startPage(PdfDocument.PageInfo.Builder(PAGE_WIDTH, PAGE_HEIGHT, 1).create())
            draw(context, page.canvas, document)
            pdf.finishPage(page)
            pdf.writeTo(output)
        } finally {
            pdf.close()
        }
    }

    @Suppress("LongMethod", "CyclomaticComplexMethod")
    internal fun draw(context: Context, canvas: Canvas, document: RecoveryKitDocument) {
        val res = context.resources
        val colors = BentoTokens.LightColors
        val ink = colors.ink.toArgb()
        val muted = colors.inkMuted.toArgb()
        val line = colors.line.toArgb()
        val sans = runCatching { ResourcesCompat.getFont(context, DesignR.font.geist_variable) }.getOrNull() ?: Typeface.SANS_SERIF
        val mono = runCatching { ResourcesCompat.getFont(context, DesignR.font.geist_mono_variable) }.getOrNull() ?: Typeface.MONOSPACE
        val width = PAGE_WIDTH - MARGIN * 2
        fun paint(size: Float, color: Int = ink, bold: Boolean = false, face: Typeface = sans) = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
            textSize = size
            this.color = color
            typeface = Typeface.create(face, if (bold) Typeface.BOLD else Typeface.NORMAL)
        }
        var y = MARGIN

        fun text(value: String, p: TextPaint, top: Float = 0f): Float {
            val layout = StaticLayout.Builder.obtain(
                value,
                0,
                value.length,
                p,
                width.toInt()
            ).setAlignment(Layout.Alignment.ALIGN_NORMAL).build()
            canvas.save()
            canvas.translate(MARGIN, y + top)
            layout.draw(canvas)
            canvas.restore()
            y += top + layout.height
            return layout.height.toFloat()
        }

        // Header: the mark and title, a rule under it.
        drawMark(canvas, MARGIN, y, 30f)
        val title = paint(20f, bold = true)
        canvas.drawText(res.getString(StringsR.string.recovery_sheet_title), MARGIN + 42f, y + 14f, title)
        canvas.drawText(res.getString(StringsR.string.recovery_sheet_tagline), MARGIN + 42f, y + 29f, paint(10f, muted))
        y += 44f
        canvas.drawLine(
            MARGIN,
            y,
            PAGE_WIDTH - MARGIN,
            y,
            Paint().apply {
                color = line
                strokeWidth = 1f
            }
        )
        y += 22f

        // Facts.
        val label = paint(11f, muted)
        val value = paint(11f, bold = true)
        val rows = buildList {
            document.accountName?.takeIf { it.isNotBlank() }?.let { add(res.getString(StringsR.string.recovery_sheet_account) to it) }
            formatDate(document.vaultCreatedAt)?.let { add(res.getString(StringsR.string.recovery_sheet_created) to it) }
            add(res.getString(StringsR.string.recovery_sheet_printed) to formatDate(document.printedAt))
        }
        for ((name, fact) in rows) {
            canvas.drawText(name, MARGIN, y + 11f, label)
            canvas.drawText(fact, MARGIN + 140f, y + 11f, value)
            y += 18f
        }
        y += 18f

        // Code box: 3 × 3 groups and the QR.
        canvas.drawText(
            res.getString(StringsR.string.recovery_code_label).uppercase(Locale.getDefault()),
            MARGIN,
            y + 10f,
            paint(9f, muted, bold = true)
        )
        y += 18f
        val boxHeight = 150f
        val box = RectF(MARGIN, y, PAGE_WIDTH - MARGIN, y + boxHeight)
        canvas.drawRoundRect(
            box,
            12f,
            12f,
            Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = ink
                style = Paint.Style.STROKE
                strokeWidth = 2f
            }
        )
        val qrSide = if (document.qr != null) 118f else 0f
        val groupsWidth = box.width() - 36f - (if (qrSide > 0) qrSide + 20f else 0f)
        val codePaint = paint(19f, bold = true, face = mono).apply {
            letterSpacing = 0.16f
            textAlign = Paint.Align.CENTER
        }
        RecoveryCodes.groups(document.code).forEachIndexed { index, group ->
            val col = index % 3
            val row = index / 3
            val cx = box.left + 18f + groupsWidth / 3f * (col + 0.5f)
            val cy = box.top + 42f + row * 38f
            canvas.drawText(group, cx, cy, codePaint)
        }
        document.qr?.let { drawQr(canvas, it, box.right - 16f - qrSide, box.top + (boxHeight - qrSide) / 2f, qrSide, ink) }
        y += boxHeight + 24f

        text(res.getString(StringsR.string.recovery_sheet_keep), paint(13f, bold = true))
        text(res.getString(StringsR.string.recovery_sheet_how_to), paint(11f, muted), top = 10f)
        y += 18f
        val warning =
            res.getString(StringsR.string.recovery_sheet_warning_title) + " " + res.getString(StringsR.string.recovery_sheet_warning)
        val warningPaint = paint(11f)
        val warningLayout = StaticLayout.Builder.obtain(warning, 0, warning.length, warningPaint, (width - 28f).toInt()).build()
        val warningBox = RectF(MARGIN, y, PAGE_WIDTH - MARGIN, y + warningLayout.height + 24f)
        canvas.drawRoundRect(
            warningBox,
            8f,
            8f,
            Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = line
                style = Paint.Style.STROKE
                strokeWidth =
                    1f
            }
        )
        canvas.save()
        canvas.translate(MARGIN + 14f, y + 12f)
        warningLayout.draw(canvas)
        canvas.restore()
        y = warningBox.bottom + 24f
        text(res.getString(StringsR.string.recovery_sheet_footer, res.getString(StringsR.string.app_name)), paint(9f, muted))
    }

    /** The Bento mark from brand.md §3 geometry (32-unit grid): lacquer box, three compartments, the ume. */
    private fun drawMark(canvas: Canvas, x: Float, y: Float, size: Float) {
        val colors = BentoTokens.LightColors
        val s = size / 32f
        val p = Paint(Paint.ANTI_ALIAS_FLAG)
        p.color = colors.ink.toArgb()
        canvas.drawRoundRect(RectF(x, y, x + 32f * s, y + 32f * s), 9f * s, 9f * s, p)
        p.color = colors.tray.toArgb()
        for ((cx, cy, w, h) in listOf(
            floatArrayOf(4.5f, 5f, 10.5f, 22f),
            floatArrayOf(17f, 5f, 10.5f, 10f),
            floatArrayOf(17f, 17f, 10.5f, 10f)
        )) {
            canvas.drawRoundRect(RectF(x + cx * s, y + cy * s, x + (cx + w) * s, y + (cy + h) * s), 3.5f * s, 3.5f * s, p)
        }
        p.color = colors.shu.toArgb()
        canvas.drawCircle(x + 22.25f * s, y + 22f * s, 2.75f * s, p)
    }

    private fun drawQr(canvas: Canvas, matrix: QrMatrix, x: Float, y: Float, side: Float, color: Int) {
        val quiet = 2
        val cell = side / (matrix.size + quiet * 2)
        val p = Paint().apply { this.color = color }
        for (row in 0 until matrix.size) {
            for (col in 0 until matrix.size) {
                if (matrix[col, row]) {
                    val left = x + (col + quiet) * cell
                    val top = y + (row + quiet) * cell
                    canvas.drawRect(left, top, left + cell + 0.2f, top + cell + 0.2f, p)
                }
            }
        }
    }

    private fun formatDate(iso: String?): String? = TrustDates.long(iso)

    private fun formatDate(instant: Instant): String = TrustDates.long(instant)
}

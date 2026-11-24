package dev.bento.engine.bridge

import android.graphics.ImageDecoder
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import kotlinx.serialization.Serializable
import java.util.concurrent.TimeUnit

@Serializable
data class OcrLine(val text: String, val box: List<Int>, val confidence: Double?)

@Serializable
data class OcrResult(val text: String, val language: String?, val lines: List<OcrLine>)

/** Maps ML Kit's recognition result to the RapidOCR-compatible shape (JVM tested through [OcrMapping]). */
object OcrMapping {
    data class RawLine(val text: String, val left: Int, val top: Int, val right: Int, val bottom: Int, val confidence: Float?, val language: String?)

    fun map(fullText: String, lines: List<RawLine>): OcrResult {
        val language = lines.mapNotNull { it.language?.takeIf { lang -> lang.isNotBlank() && lang != "und" } }
            .groupingBy { it }.eachCount().maxByOrNull { it.value }?.key
        return OcrResult(
            text = fullText,
            language = language,
            lines = lines.map { line ->
                OcrLine(
                    text = line.text,
                    box = listOf(line.left, line.top, (line.right - line.left).coerceAtLeast(0), (line.bottom - line.top).coerceAtLeast(0)),
                    confidence = line.confidence?.toDouble()?.takeIf { it in 0.0..1.0 },
                )
            },
        )
    }
}

/** ML Kit Text Recognition v2, bundled Latin model: on-device, no network, no Play services dependency. */
class MlKitOcr : Ocr {
    private val recognizer by lazy { TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS) }

    override fun available(): Boolean = true

    override fun recognize(source: String, maxSide: Int): String = bridgeCall {
        val parsed = BridgeSource.parse(source)
        val bitmap = parsed.openPfd().use { pfd ->
            val imageSource = ImageDecoder.createSource {
                android.content.res.AssetFileDescriptor(
                    android.os.ParcelFileDescriptor.dup(pfd.fileDescriptor),
                    0,
                    android.content.res.AssetFileDescriptor.UNKNOWN_LENGTH,
                )
            }
            ImageDecoder.decodeBitmap(imageSource) { decoder, info, _ ->
                val target = MediaMath.fit(info.size.width, info.size.height, maxSide)
                decoder.setTargetSize(target.width, target.height)
                decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
            }
        }
        try {
            val text: Text = Tasks.await(recognizer.process(InputImage.fromBitmap(bitmap, 0)), TIMEOUT_S, TimeUnit.SECONDS)
            val lines = text.textBlocks.flatMap { block ->
                block.lines.map { line ->
                    val box = line.boundingBox
                    OcrMapping.RawLine(
                        text = line.text,
                        left = box?.left ?: 0,
                        top = box?.top ?: 0,
                        right = box?.right ?: 0,
                        bottom = box?.bottom ?: 0,
                        confidence = line.confidence,
                        language = line.recognizedLanguage,
                    )
                }
            }
            BridgeJson.encodeToString(OcrResult.serializer(), OcrMapping.map(text.text, lines))
        } catch (timeout: java.util.concurrent.TimeoutException) {
            throw BridgeException(BridgeException.CANCELLED, "ocr timed out", timeout)
        } catch (failure: java.util.concurrent.ExecutionException) {
            throw BridgeException(BridgeException.IO, failure.cause?.message ?: "ocr failed", failure)
        } finally {
            bitmap.recycle()
        }
    }

    private companion object {
        const val TIMEOUT_S = 60L
    }
}

package dev.bento.background

import android.app.Activity
import android.content.ClipData
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import com.google.mlkit.vision.documentscanner.GmsDocumentScannerOptions
import com.google.mlkit.vision.documentscanner.GmsDocumentScanning
import com.google.mlkit.vision.documentscanner.GmsDocumentScanningResult

/**
 * Launcher shortcuts `Subir fotos` and `Escanear documento` (product/android.md §7): opens the system photo picker or
 * the on-device document scanner straight from the icon, then hands the result to the share-to-Bento sheet (which
 * asks where to save it). Invisible; finishes as soon as the picker closes.
 */
class ShortcutActivity : ComponentActivity() {
    private val pickMedia = registerForActivityResult(ActivityResultContracts.PickMultipleVisualMedia()) { uris -> forward(uris) }

    private val scan = registerForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { result ->
        val pdf = GmsDocumentScanningResult.fromActivityResultIntent(result.data)?.pdf?.uri
        forward(if (result.resultCode == Activity.RESULT_OK) listOfNotNull(pdf) else emptyList())
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState != null) return
        when (intent?.action) {
            ACTION_UPLOAD_PHOTOS -> pickMedia.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageAndVideo))
            ACTION_SCAN_DOCUMENT -> startScanner()
            else -> finish()
        }
    }

    private fun startScanner() {
        val options = GmsDocumentScannerOptions.Builder()
            .setGalleryImportAllowed(true)
            .setResultFormats(GmsDocumentScannerOptions.RESULT_FORMAT_PDF)
            .setScannerMode(GmsDocumentScannerOptions.SCANNER_MODE_FULL)
            .build()
        GmsDocumentScanning.getClient(options).getStartScanIntent(this)
            .addOnSuccessListener { sender -> scan.launch(IntentSenderRequest.Builder(sender).build()) }
            // No scanner module (no Play services): Archivos still offers every upload path.
            .addOnFailureListener { openApp() }
    }

    private fun forward(uris: List<Uri>) {
        if (uris.isNotEmpty()) startActivity(ShortcutForwarding.shareIntent(packageName, uris))
        finish()
    }

    private fun openApp() {
        packageManager.getLaunchIntentForPackage(packageName)?.let(::startActivity)
        finish()
    }

    companion object {
        const val ACTION_UPLOAD_PHOTOS = "dev.bento.action.UPLOAD_PHOTOS"
        const val ACTION_SCAN_DOCUMENT = "dev.bento.action.SCAN_DOCUMENT"
    }
}

/** The explicit share intent to Bento's own share sheet (agent 40's `ShareActivity`). */
object ShortcutForwarding {
    const val SHARE_ACTIVITY = "dev.bento.app.ShareActivity"

    fun shareIntent(packageName: String, uris: List<Uri>): Intent {
        val intent = if (uris.size == 1) {
            Intent(Intent.ACTION_SEND).putExtra(Intent.EXTRA_STREAM, uris.first())
        } else {
            Intent(Intent.ACTION_SEND_MULTIPLE).putParcelableArrayListExtra(Intent.EXTRA_STREAM, ArrayList(uris))
        }
        val clip = ClipData.newRawUri(null, uris.first()).apply { uris.drop(1).forEach { addItem(ClipData.Item(it)) } }
        return intent.setClassName(packageName, SHARE_ACTIVITY)
            .setType("*/*")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
            .apply { clipData = clip }
    }
}

package dev.bento.feature.recovery

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.compose.CameraXViewfinder
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.core.SurfaceRequest
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LifecycleResumeEffect
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoIconSize
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.theme.BentoHaptic
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.theme.bentoHaptics
import dev.bento.strings.R as StringsR
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Renders the live camera and reports decoded QR payloads. A slot so JVM tests and screenshots pass a still
 * placeholder instead of CameraX.
 */
typealias CameraSlot = @Composable BoxScope.(onDecoded: (String) -> Unit) -> Unit

/** Real camera: CameraX preview + ML Kit barcode scanning (bundled model, on-device, QR only). */
val CameraXSlot: CameraSlot = { onDecoded -> CameraPreview(onDecoded, Modifier.fillMaxSize()) }

/**
 * Camera permission state for the in-app scanner (product/android.md §6: asked only when the scanner opens, never
 * twice in a session; a denial falls back to typing the code).
 */
enum class CameraAccess { Unknown, Granted, Denied }

/**
 * Full-bleed scanner area with the branded frame. Shows a one-sentence rationale and `Permitir cámara` until the
 * permission is granted; if denied it explains that the code field below still works (no dead end). Each new
 * payload that [accept] returns true for plays the `CONFIRM` haptic; rejected ones play `REJECT` once.
 */
@Composable
fun QrScannerPanel(
    onCode: (String) -> Unit,
    accept: (String) -> Boolean,
    modifier: Modifier = Modifier,
    camera: CameraSlot = CameraXSlot,
    access: CameraAccess = rememberCameraAccess(),
    onRequestAccess: () -> Unit = {},
    onOpenSettings: () -> Unit = {},
    hint: String = stringResource(StringsR.string.recovery_scanner_hint),
    rejectedMessage: String? = null
) {
    val c = BentoTheme.colors
    val haptics = bentoHaptics()
    var lastRejected by remember { mutableStateOf<String?>(null) }
    val handled = remember { AtomicBoolean(false) }
    Box(
        modifier
            .fillMaxWidth()
            .widthIn(max = 480.dp)
            .aspectRatio(1f)
            .clip(BentoShapes.hero)
            .background(c.ink),
        contentAlignment = Alignment.Center
    ) {
        when (access) {
            CameraAccess.Granted -> {
                camera { payload ->
                    if (accept(payload)) {
                        if (handled.compareAndSet(false, true)) {
                            haptics.perform(BentoHaptic.Confirm)
                            onCode(payload)
                        }
                    } else if (payload != lastRejected) {
                        lastRejected = payload
                        haptics.perform(BentoHaptic.Reject)
                    }
                }
                ScannerFrame()
                Text(
                    text = if (lastRejected != null && rejectedMessage != null) rejectedMessage else hint,
                    color = c.white,
                    style = BentoTheme.typography.label,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.align(Alignment.BottomCenter).padding(20.dp)
                )
            }

            CameraAccess.Unknown -> CameraRationale(
                body = stringResource(StringsR.string.recovery_scanner_rationale),
                action = stringResource(StringsR.string.recovery_scanner_allow),
                onAction = onRequestAccess
            )

            CameraAccess.Denied -> CameraRationale(
                body = stringResource(StringsR.string.recovery_scanner_denied),
                action = stringResource(StringsR.string.recovery_scanner_open_settings),
                onAction = onOpenSettings,
                denied = true
            )
        }
    }
}

@Composable
private fun CameraRationale(body: String, action: String, onAction: () -> Unit, denied: Boolean = false) {
    val c = BentoTheme.colors
    Column(
        Modifier.fillMaxSize().background(c.subtle).padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.CenterVertically)
    ) {
        BentoIcon(
            if (denied) BentoIcons.CameraOff else BentoIcons.ScanLine,
            contentDescription = null,
            tint = c.inkMuted,
            size = BentoIconSize.Large
        )
        Text(body, color = c.ink, style = BentoTheme.typography.body, textAlign = TextAlign.Center)
        BentoButton(action, onAction, variant = if (denied) BentoButtonVariant.Secondary else BentoButtonVariant.Primary)
    }
}

/** Four rounded corner marks of the "compartment" the code should sit in. */
@Composable
private fun BoxScope.ScannerFrame() {
    val c = BentoTheme.colors
    val label = stringResource(StringsR.string.recovery_scanner_viewfinder)
    Canvas(
        Modifier
            .matchParentSize()
            .padding(48.dp)
            .semantics {
                contentDescription = label
                role = Role.Image
            }
    ) {
        val stroke = Stroke(width = 4.dp.toPx())
        val arm = size.minDimension * 0.22f
        val r = 18.dp.toPx()
        val w = size.width
        val h = size.height
        // Each corner as a rounded rect clipped to its arm length reads as one stroke with a soft corner.
        listOf(Offset(0f, 0f), Offset(w - arm, 0f), Offset(0f, h - arm), Offset(w - arm, h - arm)).forEach { origin ->
            drawRoundRect(c.white, origin, Size(arm, arm), CornerRadius(r), style = stroke, alpha = 0.9f)
        }
    }
}

@androidx.annotation.OptIn(markerClass = [androidx.camera.core.ExperimentalGetImage::class])
@Composable
private fun CameraPreview(onDecoded: (String) -> Unit, modifier: Modifier) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current
    val current by rememberUpdatedState(onDecoded)
    var request by remember { mutableStateOf<SurfaceRequest?>(null) }
    DisposableEffect(lifecycle) {
        val executor = Executors.newSingleThreadExecutor()
        val scanner = BarcodeScanning.getClient(BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build())
        val preview = Preview.Builder().build().apply { setSurfaceProvider { request = it } }
        val analysis = ImageAnalysis.Builder().setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
        analysis.setAnalyzer(executor) { proxy ->
            val media = proxy.image
            if (media == null) {
                proxy.close()
                return@setAnalyzer
            }
            scanner.process(InputImage.fromMediaImage(media, proxy.imageInfo.rotationDegrees))
                .addOnSuccessListener { codes -> codes.firstNotNullOfOrNull { it.rawValue }?.let { value -> current(value) } }
                .addOnCompleteListener { proxy.close() }
        }
        val future = ProcessCameraProvider.getInstance(context)
        var provider: ProcessCameraProvider? = null
        future.addListener({
            provider = runCatching { future.get() }.getOrNull()
            runCatching { provider?.bindToLifecycle(lifecycle, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis) }
        }, ContextCompat.getMainExecutor(context))
        onDispose {
            runCatching { provider?.unbind(preview, analysis) }
            analysis.clearAnalyzer()
            scanner.close()
            executor.shutdown()
        }
    }
    request?.let { CameraXViewfinder(surfaceRequest = it, modifier = modifier) }
}

/** Reads the current camera permission; never asks by itself. */
@Composable
fun rememberCameraAccess(): CameraAccess {
    val context = LocalContext.current
    return if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
        CameraAccess.Granted
    } else {
        CameraAccess.Unknown
    }
}

/** Camera permission requester: [access], a [request] for the one in-context ask, and the app settings fallback. */
class CameraPermission internal constructor(val access: CameraAccess, val request: () -> Unit, val openSettings: () -> Unit)

@Composable
fun rememberCameraPermission(): CameraPermission {
    val context = LocalContext.current
    val initial = rememberCameraAccess()
    var access by rememberSaveable { mutableStateOf(initial) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        access = if (granted) CameraAccess.Granted else CameraAccess.Denied
    }
    // Coming back from the system settings with the permission granted turns the camera on.
    LifecycleResumeEffect(Unit) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            access = CameraAccess.Granted
        }
        onPauseOrDispose {}
    }
    return CameraPermission(
        access = access,
        request = { launcher.launch(Manifest.permission.CAMERA) },
        openSettings = { context.openAppSettings() }
    )
}

fun Context.openAppSettings() {
    val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null))
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    runCatching { startActivity(intent) }
}

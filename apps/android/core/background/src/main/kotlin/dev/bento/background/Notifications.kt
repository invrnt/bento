package dev.bento.background

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import dev.bento.designsystem.R as DesignR
import dev.bento.engine.bridge.EngineEvent
import dev.bento.strings.R as StringsR

/** Channels, ids and builders for every Bento notification (product/android.md §8). No marketing, ever. */
object BentoNotifications {
    const val CHANNEL_TRANSFERS = "transfers"
    const val CHANNEL_ATTENTION = "attention"
    const val CHANNEL_DEVICES = "devices"

    /** The single ongoing transfer notification (UIDT / dataSync FGS). */
    const val ID_TRANSFER = 1001
    const val ID_TRANSFER_SUMMARY = 1002
    private const val ID_ATTENTION_BASE = 2000
    private const val ID_DEVICES_BASE = 3000

    /** Set by the app: the intent that opens MainActivity (deep link target for taps). */
    @Volatile
    var launchIntent: (Context) -> Intent? = { it.packageManager.getLaunchIntentForPackage(it.packageName) }

    fun createChannels(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannels(
            listOf(
                NotificationChannel(
                    CHANNEL_TRANSFERS,
                    context.getString(StringsR.string.bento_channel_transfers),
                    NotificationManager.IMPORTANCE_LOW
                ).apply {
                    description = context.getString(StringsR.string.bento_channel_transfers_description)
                    setShowBadge(false)
                    setSound(null, null)
                },
                NotificationChannel(
                    CHANNEL_ATTENTION,
                    context.getString(StringsR.string.bento_channel_attention),
                    NotificationManager.IMPORTANCE_DEFAULT
                ).apply {
                    description = context.getString(StringsR.string.bento_channel_attention_description)
                },
                NotificationChannel(
                    CHANNEL_DEVICES,
                    context.getString(StringsR.string.bento_channel_devices),
                    NotificationManager.IMPORTANCE_HIGH
                ).apply {
                    description = context.getString(StringsR.string.bento_channel_devices_description)
                }
            )
        )
    }

    fun canPost(context: Context): Boolean =
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED &&
            NotificationManagerCompat.from(context).areNotificationsEnabled()

    /** Ongoing progress notification; [progress] null shows "Preparando…" (indeterminate). */
    fun transfer(context: Context, progress: EngineEvent.TransferProgress?): Notification {
        val kind = progress?.kind ?: EngineEvent.TransferKind.UNKNOWN
        val title = context.getString(
            when (kind) {
                EngineEvent.TransferKind.BACKUP -> StringsR.string.bento_transfer_title_backup
                EngineEvent.TransferKind.UPLOAD -> StringsR.string.bento_transfer_title_upload
                EngineEvent.TransferKind.DOWNLOAD -> StringsR.string.bento_transfer_title_download
                EngineEvent.TransferKind.IMPORT -> StringsR.string.bento_transfer_title_import
                EngineEvent.TransferKind.UNKNOWN -> StringsR.string.bento_transfer_title_generic
            }
        )
        val text = when {
            progress == null || progress.total <= 0 -> context.getString(StringsR.string.bento_transfer_preparing)

            progress.paused -> context.getString(StringsR.string.bento_transfer_paused)

            else -> context.resources.getQuantityString(
                StringsR.plurals.bento_transfer_progress,
                progress.total,
                progress.done,
                progress.total
            )
        }
        val builder = NotificationCompat.Builder(context, CHANNEL_TRANSFERS)
            .setSmallIcon(DesignR.drawable.ic_stat_bento)
            .setContentTitle(title)
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setContentIntent(openApp(context))
            .addAction(0, context.getString(StringsR.string.bento_transfer_pause), TransferActionReceiver.pauseIntent(context))
        if (progress == null || progress.bytesTotal <= 0) {
            builder.setProgress(0, 0, true)
        } else {
            builder.setProgress(
                PROGRESS_MAX,
                (progress.bytesDone * PROGRESS_MAX / progress.bytesTotal).toInt().coerceIn(0, PROGRESS_MAX),
                false
            )
        }
        return builder.build()
    }

    fun backupSummary(context: Context, count: Int): Notification = NotificationCompat.Builder(context, CHANNEL_TRANSFERS)
        .setSmallIcon(DesignR.drawable.ic_stat_bento)
        .setContentTitle(context.resources.getQuantityString(StringsR.plurals.bento_transfer_finished_backup, count, count))
        .setAutoCancel(true)
        .setContentIntent(openApp(context))
        .build()

    fun attention(context: Context): Notification = NotificationCompat.Builder(context, CHANNEL_ATTENTION)
        .setSmallIcon(DesignR.drawable.ic_stat_bento)
        .setContentTitle(context.getString(StringsR.string.bento_attention_title))
        .setContentText(context.getString(StringsR.string.bento_attention_text))
        .setAutoCancel(true)
        .setContentIntent(openApp(context))
        .build()

    fun device(context: Context, title: String): Notification = NotificationCompat.Builder(context, CHANNEL_DEVICES)
        .setSmallIcon(DesignR.drawable.ic_stat_bento)
        .setContentTitle(title)
        .setContentText(context.getString(StringsR.string.bento_device_review_text))
        .setPriority(NotificationCompat.PRIORITY_HIGH)
        .setAutoCancel(true)
        .setContentIntent(openApp(context))
        .build()

    fun attentionId(code: String): Int = ID_ATTENTION_BASE + (code.hashCode() and 0x3FF)

    fun deviceId(key: String): Int = ID_DEVICES_BASE + (key.hashCode() and 0x3FF)

    private fun openApp(context: Context): PendingIntent? = launchIntent(context)?.let {
        PendingIntent.getActivity(context, 0, it, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    private const val PROGRESS_MAX = 1000
}

/** Renders [NotificationDecision]s; collects the engine's Notifier events for the app's lifetime. */
class NotificationDriver(private val context: Context, private val policy: NotificationPolicy = NotificationPolicy()) {
    @Volatile
    var lastProgress: EngineEvent.TransferProgress? = null
        private set

    @android.annotation.SuppressLint("MissingPermission")
    fun handle(event: EngineEvent) {
        val decision = policy.decide(event)
        if (decision is NotificationDecision.Progress) lastProgress = decision.event
        if (!BentoNotifications.canPost(context)) return
        val manager = NotificationManagerCompat.from(context)
        when (decision) {
            NotificationDecision.Ignore -> Unit

            is NotificationDecision.Progress -> if (TransferState.active) {
                manager.notify(BentoNotifications.ID_TRANSFER, BentoNotifications.transfer(context, decision.event))
            }

            is NotificationDecision.Finished -> {
                lastProgress = null
                if (decision.summaryCount > 0) {
                    manager.notify(BentoNotifications.ID_TRANSFER_SUMMARY, BentoNotifications.backupSummary(context, decision.summaryCount))
                }
            }

            is NotificationDecision.Attention ->
                manager.notify(BentoNotifications.attentionId(decision.code), BentoNotifications.attention(context))

            is NotificationDecision.DeviceRequest -> manager.notify(
                BentoNotifications.deviceId(decision.requestId),
                BentoNotifications.device(context, context.getString(StringsR.string.bento_device_request_title))
            )

            is NotificationDecision.DeviceAdded -> manager.notify(
                BentoNotifications.deviceId(decision.deviceId),
                BentoNotifications.device(context, context.getString(StringsR.string.bento_device_added_title, decision.name))
            )
        }
    }
}

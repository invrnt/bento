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
import dev.bento.designsystem.format.BentoFormat
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
        val content = NotificationContent.transfer(context, progress)
        val paused = progress?.paused == true
        val builder = NotificationCompat.Builder(context, CHANNEL_TRANSFERS)
            .setSmallIcon(DesignR.drawable.ic_stat_bento)
            .setContentTitle(content.title)
            .setContentText(content.text)
            .setSubText(content.subText)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setContentIntent(openApp(context, OpenTarget.Activity))
            .addAction(
                0,
                context.getString(if (paused) StringsR.string.common_action_resume else StringsR.string.bento_transfer_pause),
                if (paused) TransferActionReceiver.resumeIntent(context) else TransferActionReceiver.pauseIntent(context)
            )
        if (progress == null || progress.bytesTotal <= 0) {
            if (progress != null && progress.total > 0) {
                builder.setProgress(progress.total, progress.done.coerceIn(0, progress.total), false)
            } else {
                builder.setProgress(0, 0, true)
            }
        } else {
            builder.setProgress(
                PROGRESS_MAX,
                (progress.bytesDone * PROGRESS_MAX / progress.bytesTotal).toInt().coerceIn(0, PROGRESS_MAX),
                false
            )
        }
        return builder.build()
    }

    /** "Listo: 18.000 fotos respaldadas", only after an initial (user-initiated) backup. */
    fun backupSummary(context: Context, count: Int): Notification = NotificationCompat.Builder(context, CHANNEL_TRANSFERS)
        .setSmallIcon(DesignR.drawable.ic_stat_bento)
        .setContentTitle(BentoFormat.plural(context.resources, StringsR.plurals.bento_transfer_finished_backup, count))
        .setContentText(context.getString(StringsR.string.activity_notif_summary_text))
        .setAutoCancel(true)
        .setContentIntent(openApp(context, OpenTarget.Backup))
        .build()

    /** One "Necesita tu atención" notification per code (coalesced by [NotificationPolicy]), with one action. */
    fun attention(context: Context, code: String, count: Int): Notification {
        val content = NotificationContent.attention(context, code, count)
        return NotificationCompat.Builder(context, CHANNEL_ATTENTION)
            .setSmallIcon(DesignR.drawable.ic_stat_bento)
            .setContentTitle(content.title)
            .setContentText(content.text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(content.text))
            .setAutoCancel(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setContentIntent(openApp(context, content.target))
            .addAction(0, content.action, openApp(context, content.target))
            .build()
    }

    /** "Un dispositivo nuevo quiere unirse" (Sync-channel fallback pairing): opens its review screen. */
    fun pairingRequest(context: Context, requestId: String, deviceName: String): Notification =
        device(context, NotificationContent.pairingRequest(context, deviceName), OpenTarget.PairingRequest(requestId))

    /** "Se añadió «Portátil de Ana»" (new device review). */
    fun deviceAdded(context: Context, deviceId: String, name: String): Notification =
        device(context, NotificationContent.deviceAdded(context, name), OpenTarget.DeviceReview(deviceId))

    private fun device(context: Context, content: NotificationText, target: OpenTarget): Notification =
        NotificationCompat.Builder(context, CHANNEL_DEVICES)
            .setSmallIcon(DesignR.drawable.ic_stat_bento)
            .setContentTitle(content.title)
            .setContentText(content.text)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_RECOMMENDATION)
            .setAutoCancel(true)
            .setContentIntent(openApp(context, target))
            .addAction(0, content.action, openApp(context, target))
            .build()

    fun attentionId(code: String): Int = ID_ATTENTION_BASE + (code.hashCode() and 0x3FF)

    fun deviceId(key: String): Int = ID_DEVICES_BASE + (key.hashCode() and 0x3FF)

    /** The app's launch intent with [target]; one PendingIntent per target so extras never collide. */
    fun openApp(context: Context, target: OpenTarget): PendingIntent? = launchIntent(context)?.let { intent ->
        val encoded = OpenTargets.encode(target)
        PendingIntent.getActivity(
            context,
            encoded.hashCode(),
            intent.putExtra(OpenTargets.EXTRA, encoded),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
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
        if (decision is NotificationDecision.Finished) lastProgress = null
        if (!BentoNotifications.canPost(context)) return
        val manager = NotificationManagerCompat.from(context)
        when (decision) {
            NotificationDecision.Ignore -> Unit

            // The ongoing notification belongs to the running transfer (UIDT / FGS); never one per file.
            is NotificationDecision.Progress -> if (TransferState.active) {
                manager.notify(BentoNotifications.ID_TRANSFER, BentoNotifications.transfer(context, decision.event))
            }

            // A completion summary only after an initial backup, i.e. one run as a user-initiated transfer.
            is NotificationDecision.Finished -> if (decision.summaryCount > 0 && TransferState.active) {
                manager.notify(BentoNotifications.ID_TRANSFER_SUMMARY, BentoNotifications.backupSummary(context, decision.summaryCount))
            }

            is NotificationDecision.Attention ->
                manager.notify(
                    BentoNotifications.attentionId(decision.code),
                    BentoNotifications.attention(context, decision.code, decision.count)
                )

            is NotificationDecision.DeviceRequest -> manager.notify(
                BentoNotifications.deviceId(decision.requestId),
                BentoNotifications.pairingRequest(context, decision.requestId, decision.deviceName)
            )

            is NotificationDecision.DeviceAdded -> manager.notify(
                BentoNotifications.deviceId(decision.deviceId),
                BentoNotifications.deviceAdded(context, decision.deviceId, decision.name)
            )
        }
    }
}

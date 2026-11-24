package dev.bento.background

import android.content.Context
import dev.bento.designsystem.format.BentoFormat
import dev.bento.engine.bridge.EngineEvent
import dev.bento.strings.R as StringsR

/** Text of one notification: [action] is its single action button, [target] where a tap leads. */
data class NotificationText(
    val title: String,
    val text: String,
    val action: String = "",
    val target: OpenTarget = OpenTarget.Activity,
    val subText: String? = null
)

/**
 * What an `attention {code}` event is about (api/android-endpoints.md §7: codes are the Activity item kinds, plus the
 * phone-only ones of product/android.md §8). Pure; each topic has one action and one destination.
 */
enum class AttentionTopic(val target: OpenTarget) {
    SignIn(OpenTarget.Reconnect),
    RecoveryKit(OpenTarget.Recovery),
    DeviceRemoved(OpenTarget.DeviceRemoved),
    StorageFull(OpenTarget.Storage),
    UploadFailed(OpenTarget.Activity),
    NewDevice(OpenTarget.Devices),
    Generic(OpenTarget.Activity)
    ;

    companion object {
        fun of(code: String): AttentionTopic = when (code) {
            "session_revoked", "signed_out", "telegram_signed_out", "reconnect" -> SignIn
            "recovery_kit" -> RecoveryKit
            "device_removed" -> DeviceRemoved
            "storage_full", "phone_storage_low", "storage_low" -> StorageFull
            "upload_failed", "backup_failed" -> UploadFailed
            "new_device" -> NewDevice
            else -> Generic
        }
    }
}

/** Notification copy per Notifier event (strings in core/strings `strings_activity.xml`); no user strings cross the bridge. */
object NotificationContent {
    fun transfer(context: Context, progress: EngineEvent.TransferProgress?): NotificationText {
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
                StringsR.plurals.activity_notif_progress,
                progress.total,
                BentoFormat.count(context.resources, progress.done),
                BentoFormat.count(context.resources, progress.total)
            )
        }
        val bytes = progress?.takeIf { it.bytesTotal > 0 && !it.paused }?.let {
            context.getString(
                StringsR.string.activity_notif_bytes,
                BentoFormat.bytes(context.resources, it.bytesDone),
                BentoFormat.bytes(context.resources, it.bytesTotal)
            )
        }
        return NotificationText(title, text, target = OpenTarget.Activity, subText = bytes)
    }

    fun attention(context: Context, code: String, count: Int): NotificationText {
        val topic = AttentionTopic.of(code)
        val res = context.resources
        return when (topic) {
            AttentionTopic.SignIn -> NotificationText(
                context.getString(StringsR.string.activity_notif_signin_title),
                context.getString(StringsR.string.activity_notif_signin_text),
                context.getString(StringsR.string.common_action_reconnect),
                topic.target
            )

            AttentionTopic.RecoveryKit -> NotificationText(
                context.getString(StringsR.string.activity_notif_kit_title),
                context.getString(StringsR.string.activity_notif_kit_text),
                context.getString(StringsR.string.activity_action_save_kit),
                topic.target
            )

            AttentionTopic.DeviceRemoved -> NotificationText(
                context.getString(StringsR.string.activity_notif_removed_title),
                context.getString(StringsR.string.activity_notif_removed_text),
                context.getString(StringsR.string.common_action_review),
                topic.target
            )

            AttentionTopic.StorageFull -> NotificationText(
                context.getString(StringsR.string.activity_notif_storage_title),
                context.getString(StringsR.string.activity_notif_storage_text),
                context.getString(StringsR.string.common_action_free_space),
                topic.target
            )

            AttentionTopic.UploadFailed -> NotificationText(
                res.getQuantityString(StringsR.plurals.activity_notif_failed_title, count, count),
                context.getString(StringsR.string.activity_notif_failed_text),
                context.getString(StringsR.string.common_action_review),
                topic.target
            )

            AttentionTopic.NewDevice -> NotificationText(
                context.getString(StringsR.string.activity_notif_new_device_title),
                context.getString(StringsR.string.bento_device_review_text),
                context.getString(StringsR.string.common_action_review),
                topic.target
            )

            AttentionTopic.Generic -> NotificationText(
                context.getString(StringsR.string.bento_attention_title),
                context.getString(StringsR.string.bento_attention_text),
                context.getString(StringsR.string.common_action_review),
                topic.target
            )
        }
    }

    fun pairingRequest(context: Context, deviceName: String): NotificationText = NotificationText(
        context.getString(StringsR.string.bento_device_request_title),
        context.getString(StringsR.string.activity_notif_request_text, deviceName),
        context.getString(StringsR.string.common_action_review)
    )

    fun deviceAdded(context: Context, name: String): NotificationText = NotificationText(
        context.getString(StringsR.string.bento_device_added_title, name),
        context.getString(StringsR.string.bento_device_review_text),
        context.getString(StringsR.string.common_action_review)
    )
}

package dev.bento.feature.settings

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.runBlocking

enum class ThemeChoice { System, Light, Dark }

/** App lock timeouts of product/android.md §9 (after the app leaves the screen). */
enum class LockTimeout(val millis: Long) { Immediately(0), OneMinute(60_000), FiveMinutes(300_000), FifteenMinutes(900_000) }

/** Purely local settings (architecture/android-runtime.md §8: DataStore); everything else lives in the backend. */
data class LocalPrefs(
    val theme: ThemeChoice = ThemeChoice.System,
    val lockEnabled: Boolean = false,
    val lockTimeout: LockTimeout = LockTimeout.Immediately,
    val hideInRecents: Boolean = true,
    /** In-app language on Android 12 and older (13+ uses the system per-app setting); empty = system. */
    val language: String = "",
    val locationNoticeShown: Boolean = false,
    /** `Ahora no` on the onboarding backup step: Fotos shows a dismissible card for 7 days (agent 39 reads it). */
    val backupPromptDismissedAt: Long? = null,
    /** The stall card's last dismissal (it comes back if the backup stalls again). */
    val stallDismissedAt: Long? = null,
    /** When the current backlog was first seen (cleared when everything is backed up); feeds the stall card. */
    val pendingSinceAt: Long? = null
)

/** DataStore-backed [LocalPrefs]; [current] is a one-time blocking read for the first frame (theme, lock). */
class LocalSettings(private val store: DataStore<Preferences>) {
    val prefs: Flow<LocalPrefs> = store.data.catch { emit(androidx.datastore.preferences.core.emptyPreferences()) }.map(::read)

    fun current(): LocalPrefs = runBlocking { prefs.first() }

    suspend fun update(transform: (LocalPrefs) -> LocalPrefs) {
        store.edit { prefs ->
            val next = transform(read(prefs))
            prefs[THEME] = next.theme.name
            prefs[LOCK] = next.lockEnabled
            prefs[LOCK_TIMEOUT] = next.lockTimeout.name
            prefs[HIDE_RECENTS] = next.hideInRecents
            prefs[LANGUAGE] = next.language
            prefs[LOCATION_NOTICE] = next.locationNoticeShown
            next.backupPromptDismissedAt?.let { prefs[PROMPT_DISMISSED] = it } ?: prefs.remove(PROMPT_DISMISSED)
            next.stallDismissedAt?.let { prefs[STALL_DISMISSED] = it } ?: prefs.remove(STALL_DISMISSED)
            next.pendingSinceAt?.let { prefs[PENDING_SINCE] = it } ?: prefs.remove(PENDING_SINCE)
        }
    }

    private fun read(prefs: Preferences) = LocalPrefs(
        theme = prefs[THEME]?.let { runCatching { ThemeChoice.valueOf(it) }.getOrNull() } ?: ThemeChoice.System,
        lockEnabled = prefs[LOCK] ?: false,
        lockTimeout = prefs[LOCK_TIMEOUT]?.let { runCatching { LockTimeout.valueOf(it) }.getOrNull() } ?: LockTimeout.Immediately,
        hideInRecents = prefs[HIDE_RECENTS] ?: true,
        language = prefs[LANGUAGE].orEmpty(),
        locationNoticeShown = prefs[LOCATION_NOTICE] ?: false,
        backupPromptDismissedAt = prefs[PROMPT_DISMISSED],
        stallDismissedAt = prefs[STALL_DISMISSED],
        pendingSinceAt = prefs[PENDING_SINCE]
    )

    companion object {
        const val FILE = "bento_local_settings"
        private val THEME = stringPreferencesKey("theme")
        private val LOCK = booleanPreferencesKey("lock_enabled")
        private val LOCK_TIMEOUT = stringPreferencesKey("lock_timeout")
        private val HIDE_RECENTS = booleanPreferencesKey("hide_in_recents")
        private val LANGUAGE = stringPreferencesKey("language")
        private val LOCATION_NOTICE = booleanPreferencesKey("location_notice_shown")
        private val PROMPT_DISMISSED = longPreferencesKey("backup_prompt_dismissed_at")
        private val STALL_DISMISSED = longPreferencesKey("stall_dismissed_at")
        private val PENDING_SINCE = longPreferencesKey("pending_since_at")

        /** The `Ahora no` card on Fotos lasts 7 days (product/android.md §4.1 step 4). */
        const val PROMPT_CARD_MS = 7 * 24 * 60 * 60_000L

        fun backupPromptVisible(prefs: LocalPrefs, backupOn: Boolean, now: Long): Boolean {
            val dismissed = prefs.backupPromptDismissedAt ?: return false
            return !backupOn && now - dismissed < PROMPT_CARD_MS
        }
    }
}

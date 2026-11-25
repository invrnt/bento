package dev.bento.feature.photos

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.mediaPrefs by preferencesDataStore(name = "bento_media")

/**
 * Purely local media UI state (architecture/android-runtime.md §8: DataStore): grid density, which plaintext
 * disclosures the person chose not to see again, and when the backup card was dismissed ("Ahora no", 7 days).
 */
@Singleton
class MediaPreferences @Inject constructor(@ApplicationContext private val context: Context) {
    private val densityKey = stringPreferencesKey("grid_density")
    private val backupCardKey = longPreferencesKey("backup_card_dismissed_at")
    private fun disclosureKey(kind: Disclosure) = booleanPreferencesKey("disclosure_hidden_${kind.name.lowercase()}")

    val density: Flow<GridDensity> = context.mediaPrefs.data.map { prefs ->
        prefs[densityKey]?.let { name -> GridDensity.entries.firstOrNull { it.name == name } } ?: GridDensity.Comfortable
    }

    suspend fun setDensity(density: GridDensity) {
        context.mediaPrefs.edit { it[densityKey] = density.name }
    }

    suspend fun disclosureHidden(kind: Disclosure): Boolean = context.mediaPrefs.data.first()[disclosureKey(kind)] ?: false

    suspend fun hideDisclosure(kind: Disclosure) {
        context.mediaPrefs.edit { it[disclosureKey(kind)] = true }
    }

    val backupCardDismissedAt: Flow<Long?> = context.mediaPrefs.data.map { it[backupCardKey] }

    suspend fun dismissBackupCard(nowMs: Long = System.currentTimeMillis()) {
        context.mediaPrefs.edit { it[backupCardKey] = nowMs }
    }
}

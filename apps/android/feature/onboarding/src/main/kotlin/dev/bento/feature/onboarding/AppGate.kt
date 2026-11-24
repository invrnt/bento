package dev.bento.feature.onboarding

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import dev.bento.api.generated.VaultStatusResponse
import dev.bento.feature.recovery.Outcome
import dev.bento.feature.recovery.VaultRepository
import dev.bento.feature.recovery.attempt
import javax.inject.Inject
import javax.inject.Singleton

/** What the app shows at start (product/android.md §4.1, §11; web `useAppGate`). */
sealed interface Gate {
    /** Bienvenida. */
    data object FirstRun : Gate

    /** This phone was attached to a cloud and lost its Telegram session: reconnect, library stays visible. */
    data object Reconnect : Gate

    /** Another device removed this phone: read-only library and `Volver a unirme`. */
    data object Removed : Gate

    /** The account has a cloud but this phone has no keys yet: join (pair, ask, or recovery code). */
    data object Locked : Gate

    /** The library (Fotos). */
    data object App : Gate
}

/** Pure decision from `GET /vault` and the "Usar solo en este teléfono" choice (JVM tested). */
fun decideGate(vault: VaultStatusResponse?, localChosen: Boolean): Gate = when (vault?.state) {
    "signed_out" -> when {
        localChosen -> Gate.App
        vault.reason == "session_closed" -> Gate.Reconnect
        vault.reason == "device_removed" -> Gate.Removed
        else -> Gate.FirstRun
    }

    "no_vault" -> if (localChosen) Gate.App else Gate.FirstRun

    "locked" -> if (vault.reason == "device_removed") Gate.Removed else Gate.Locked

    // local_only, bootstrapping, ready — and an unreadable status never blocks the library.
    else -> Gate.App
}

/**
 * Small synchronous store read before the first frame so a returning person lands in Fotos instantly
 * (principle 1, "never opens to a spinner"). Holds only two booleans; nothing secret.
 */
@Singleton
class GateStore @Inject constructor(@ApplicationContext context: Context) {
    private val prefs = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    /** The last decision was the library. */
    var cachedApp: Boolean
        get() = prefs.getBoolean(KEY_APP, false)
        set(value) = prefs.edit().putBoolean(KEY_APP, value).apply()

    /** "Usar solo en este teléfono": the person chose not to connect Telegram on this phone. */
    var localMode: Boolean
        get() = prefs.getBoolean(KEY_LOCAL, false)
        set(value) = prefs.edit().putBoolean(KEY_LOCAL, value).apply()

    private companion object {
        const val FILE = "bento_gate"
        const val KEY_APP = "app"
        const val KEY_LOCAL = "local_mode"
    }
}

/** Resolves the gate against the backend and remembers whether it was the library. */
@Singleton
class AppGateResolver @Inject constructor(private val vault: VaultRepository, private val store: GateStore) {
    /** Instant guess for the first frame. */
    fun cached(): Gate = if (store.cachedApp) Gate.App else Gate.FirstRun

    /** Null when the vault status could not be read (keep what is on screen). */
    suspend fun resolve(): Gate? {
        val status = (attempt { vault.status() } as? Outcome.Ok)?.value ?: return null
        val gate = decideGate(status, store.localMode)
        store.cachedApp = gate == Gate.App || gate == Gate.Reconnect || gate == Gate.Removed
        return gate
    }

    fun chooseLocalMode() {
        store.localMode = true
        store.cachedApp = true
    }

    /** Finished onboarding or joined: the library is the start destination from now on. */
    fun finishedSetup() {
        store.localMode = false
        store.cachedApp = true
    }
}

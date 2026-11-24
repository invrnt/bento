package dev.bento.app

import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import dev.bento.engine.di.ApplicationScope
import dev.bento.feature.files.ContentFiles
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * SEC-04: decrypted copies in `cacheDir/share` must not outlive their TTL in a process that lives for days. Prunes
 * expired copies (revoking their URI grants) every [PERIOD_MS] while the process lives and whenever the app leaves
 * the foreground. Start-up already prunes everything (`ContentFiles` is created with `prune(everything = true)`).
 */
@Singleton
class ShareCacheJanitor @Inject constructor(
    private val content: ContentFiles,
    @ApplicationScope private val scope: CoroutineScope
) : DefaultLifecycleObserver {
    fun start() {
        ProcessLifecycleOwner.get().lifecycle.addObserver(this)
        scope.launch(Dispatchers.IO) {
            while (isActive) {
                delay(PERIOD_MS)
                runCatching { content.prune() }
            }
        }
    }

    override fun onStop(owner: LifecycleOwner) {
        scope.launch(Dispatchers.IO) { runCatching { content.prune() } }
    }

    private companion object {
        const val PERIOD_MS = 10 * 60_000L
    }
}

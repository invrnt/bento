package dev.bento.app

import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import dev.bento.engine.BentoEngine
import dev.bento.engine.EngineHolder
import dev.bento.engine.EngineLease

/** Holds the `ui` engine holder while an activity is started (architecture/android-runtime.md §3). */
class EngineUiHolder(private val engine: BentoEngine) : DefaultLifecycleObserver {
    private var lease: EngineLease? = null

    override fun onStart(owner: LifecycleOwner) {
        if (lease == null) lease = engine.acquire(EngineHolder.Ui)
    }

    override fun onStop(owner: LifecycleOwner) {
        lease?.close()
        lease = null
    }
}

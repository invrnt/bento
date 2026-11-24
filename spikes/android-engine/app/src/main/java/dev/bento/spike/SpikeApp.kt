package dev.bento.spike

import android.app.Application

class SpikeApp : Application() {
    override fun onCreate() {
        super.onCreate()
        // Interpreter warm-up starts immediately on a background thread; the first frame never waits for it.
        Engine.warmUp(this)
    }
}

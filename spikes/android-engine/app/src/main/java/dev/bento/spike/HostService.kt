package dev.bento.spike

import android.app.Service
import android.content.Intent
import android.os.Binder
import android.os.IBinder
import org.json.JSONObject
import java.io.File

/**
 * Pairing stand-in for the desktop host: a second interpreter in process `:host` with its own data directory,
 * sharing the fake cloud directory with the guest (main process). Spike only: its port and token are written to
 * app-private `files/host.json` so the guest-side scenario can drive it.
 */
class HostService : Service() {
    // The Activity binds with BIND_IMPORTANT: an unbound started service in its own process is frozen by the
    // cached-app freezer once the app leaves the foreground (observed on API 35), which hangs its API.
    override fun onBind(intent: Intent?): IBinder = Binder()

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val options = JSONObject(intent?.getStringExtra("options") ?: "{}")
        if (!options.has("data_name")) options.put("data_name", "bento-host")
        val out = File(filesDir, "host.json")
        Thread({
            val state = try {
                val ready = Engine.ensureStarted(options)
                JSONObject().put("port", Engine.port).put("token", Engine.apiToken).put("ready", ready)
            } catch (t: Throwable) {
                JSONObject().put("error", t.toString())
            }
            out.writeText(state.toString())
        }, "bento-host-start").start()
        return START_NOT_STICKY
    }
}

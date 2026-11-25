package dev.bento.engine

import android.app.Service
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Binder
import android.os.IBinder

/**
 * Keeps the app process out of the cached (frozen) state while the engine runs (spike finding §4.1).
 * Started (so the process ranks as a service process, not cached, after the UI goes away) and bound
 * (so it is not torn down between start requests). Not a foreground service: transfers that must survive
 * app close use UIDT jobs / the `dataSync` FGS in `core/background`, which are holders of their own.
 */
class EngineService : Service() {
    private val binder = Binder()

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_NOT_STICKY
}

/** [ProcessKeeper] backed by [EngineService]. */
class ServiceProcessKeeper(private val context: Context, private val log: EngineLog = EngineLog.None) : ProcessKeeper {
    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, service: IBinder?) = Unit

        override fun onServiceDisconnected(name: ComponentName?) = Unit
    }
    private var bound = false
    private var started = false

    @Synchronized
    override fun keepAlive() {
        val intent = Intent(context, EngineService::class.java)
        if (!started) {
            started = try {
                context.startService(intent) != null
            } catch (notAllowed: IllegalStateException) {
                // Background start restriction: the calling job/FGS holder already keeps the process alive.
                log.info("EngineService start deferred: ${notAllowed.javaClass.simpleName}")
                false
            }
        }
        if (!bound) bound = context.bindService(intent, connection, Context.BIND_AUTO_CREATE or Context.BIND_IMPORTANT)
    }

    @Synchronized
    override fun release() {
        if (bound) {
            runCatching { context.unbindService(connection) }
            bound = false
        }
        if (started) {
            context.stopService(Intent(context, EngineService::class.java))
            started = false
        }
    }
}

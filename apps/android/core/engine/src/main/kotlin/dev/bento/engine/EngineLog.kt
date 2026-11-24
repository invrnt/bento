package dev.bento.engine

import android.util.Log

/** Engine diagnostics. Messages pass through [Redaction]; release builds never write to logcat. */
interface EngineLog {
    fun info(message: String)

    fun warn(message: String, error: Throwable? = null)

    fun error(message: String, error: Throwable? = null)

    object None : EngineLog {
        override fun info(message: String) = Unit

        override fun warn(message: String, error: Throwable?) = Unit

        override fun error(message: String, error: Throwable?) = Unit
    }

    /** Debug builds: redacted logcat. */
    class Logcat(private val tag: String = "BentoEngine") : EngineLog {
        override fun info(message: String) {
            Log.i(tag, Redaction.redact(message))
        }

        override fun warn(message: String, error: Throwable?) {
            Log.w(tag, Redaction.redact(message + (error?.let { ": ${it.javaClass.simpleName} ${it.message}" } ?: "")))
        }

        override fun error(message: String, error: Throwable?) {
            Log.e(tag, Redaction.redact(message + (error?.let { ": ${it.javaClass.simpleName} ${it.message}" } ?: "")))
        }
    }
}

/** Removes bearer tokens, the registered secrets, and long key-like strings from diagnostic text. */
object Redaction {
    private val secrets = java.util.concurrent.CopyOnWriteArraySet<String>()
    private val bearer = Regex("(?i)(bearer\\s+)[A-Za-z0-9._~+/=-]+")
    private val keyLike = Regex("[A-Za-z0-9_-]{40,}")

    fun register(secret: String) {
        if (secret.length >= 8) secrets += secret
    }

    fun redact(text: String): String {
        var out = text
        for (secret in secrets) out = out.replace(secret, "<redacted>")
        out = bearer.replace(out) { "${it.groupValues[1]}<redacted>" }
        return keyLike.replace(out, "<redacted>")
    }
}

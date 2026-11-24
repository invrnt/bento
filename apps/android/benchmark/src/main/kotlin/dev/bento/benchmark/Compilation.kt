package dev.bento.benchmark

import androidx.benchmark.macro.BaselineProfileMode
import androidx.benchmark.macro.CompilationMode
import dev.bento.benchmark.common.BentoDevice
import dev.bento.benchmark.common.LibrarySeeder

/**
 * The two compilation states every benchmark compares: no AOT at all (worst case right after install) and the
 * shipped Baseline Profile (`Require` fails when the APK carries no profile, so a missing profile cannot pass as
 * "no difference"). `-e bento.compilation none|profile` runs one of them.
 */
object Compilation {
    @JvmStatic
    fun modes(): List<Array<Any>> {
        val all = listOf<Array<Any>>(
            arrayOf("none", CompilationMode.None()),
            arrayOf("profile", CompilationMode.Partial(BaselineProfileMode.Require))
        )
        val only = BentoDevice.argument("bento.compilation", "")
        return if (only.isEmpty()) all else all.filter { it[0] == only }
    }

    /** Signs in and seeds once per test class (idempotent; the first run on a cleared app takes a while). */
    fun seed() {
        BentoDevice.spanish()
        val endpoint = BentoDevice.ready()
        LibrarySeeder.ensureLibrary(endpoint)
        BentoDevice.forceStop()
    }
}

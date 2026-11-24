package dev.bento.app

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.tracing.trace
import dagger.hilt.android.AndroidEntryPoint
import dev.bento.app.navigation.BentoApp
import dev.bento.app.navigation.DeepLinks
import dev.bento.app.navigation.Navigator
import dev.bento.app.tempdesign.TempBentoTheme
import dev.bento.engine.BentoEngine
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    @Inject lateinit var engine: BentoEngine

    private val navigator = Navigator()

    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        lifecycle.addObserver(EngineUiHolder(engine))
        if (savedInstanceState == null) handleLink(intent)
        trace("bento.app.setContent") {
            setContent {
                val state by engine.state.collectAsStateWithLifecycle()
                val nav = remember { navigator }
                TempBentoTheme {
                    BentoApp(navigator = nav, engineState = state, onExit = ::finish)
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleLink(intent)
    }

    private fun handleLink(intent: Intent?) {
        if (intent?.action != Intent.ACTION_VIEW) return
        val siteHost = BuildConfig.SITE_URL.removePrefix("https://").substringBefore('/').ifEmpty { null }
        DeepLinks.parse(intent.dataString, siteHost)?.let { navigator.navigate(it) }
    }
}

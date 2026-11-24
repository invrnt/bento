package dev.bento.app

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.tracing.trace
import dagger.hilt.android.AndroidEntryPoint
import dev.bento.app.navigation.BentoApp
import dev.bento.app.navigation.DeepLinks
import dev.bento.app.navigation.Navigator
import dev.bento.app.navigation.StartRouter
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.engine.BentoEngine
import dev.bento.feature.onboarding.AppGateResolver
import javax.inject.Inject
import kotlinx.coroutines.launch

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    @Inject lateinit var engine: BentoEngine

    @Inject lateinit var gate: AppGateResolver

    private lateinit var navigator: Navigator
    private lateinit var startRouter: StartRouter

    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        lifecycle.addObserver(EngineUiHolder(engine))
        // First frame from the cached gate (never a spinner); the engine's answer corrects it below.
        navigator = Navigator(StartRouter.initialStack(gate.cached()))
        startRouter = StartRouter(navigator)
        if (savedInstanceState == null) handleLink(intent)
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) { gate.resolve()?.let(startRouter::apply) }
        }
        trace("bento.app.setContent") {
            setContent {
                val state by engine.state.collectAsStateWithLifecycle()
                val nav = remember { navigator }
                BentoTheme {
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

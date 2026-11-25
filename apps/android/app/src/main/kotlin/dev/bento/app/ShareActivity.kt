package dev.bento.app

import android.app.Activity
import android.content.Intent
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import dagger.hilt.android.AndroidEntryPoint
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.trace.InteractionTrace
import dev.bento.engine.BentoEngine
import dev.bento.feature.share.ShareSheetHost
import javax.inject.Inject

/**
 * Translucent share-target shell (ACTION_SEND / SEND_MULTIPLE / VIEW, Direct Share). Holds the `ui` holder while
 * visible so the engine is warm; the sheet (`feature/share`) hands the streams over and the activity finishes at once,
 * without an exit animation, so the sending app is back within 200 ms (product/android.md §4.9).
 */
@AndroidEntryPoint
class ShareActivity : ComponentActivity() {
    @Inject lateinit var engine: BentoEngine

    private var shared: Intent? by mutableStateOf(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        lifecycle.addObserver(EngineUiHolder(engine))
        shared = intent
        setContent {
            BentoTheme {
                ShareSheetHost(intent = shared, onFinish = ::finishFast)
            }
        }
    }

    override fun onPause() {
        super.onPause()
        InteractionTrace.end(InteractionTrace.SHARE_DISMISS)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        shared = intent
    }

    private fun finishFast() {
        finish()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            overrideActivityTransition(Activity.OVERRIDE_TRANSITION_CLOSE, 0, 0)
        } else {
            @Suppress("DEPRECATION")
            overridePendingTransition(0, 0)
        }
    }
}

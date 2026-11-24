package dev.bento.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import dagger.hilt.android.AndroidEntryPoint
import dev.bento.app.navigation.Placeholder
import dev.bento.app.tempdesign.TempBentoTheme
import dev.bento.engine.BentoEngine
import javax.inject.Inject

/**
 * Translucent share-target shell (ACTION_SEND / SEND_MULTIPLE). Holds the `ui` holder while visible so the
 * engine is warm; the sheet content (`feature/share`) is agent 40's — it replaces the placeholder below.
 */
@AndroidEntryPoint
class ShareActivity : ComponentActivity() {
    @Inject lateinit var engine: BentoEngine

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        lifecycle.addObserver(EngineUiHolder(engine))
        setContent {
            TempBentoTheme {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
                    Surface(Modifier.fillMaxWidth(), tonalElevation = 3.dp, color = MaterialTheme.colorScheme.surface) {
                        Box(Modifier.padding(24.dp)) { Placeholder("Compartir") }
                    }
                }
            }
        }
    }
}

package dev.bento.designsystem.kitchensink

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoDialog
import dev.bento.designsystem.component.BentoSheet
import dev.bento.designsystem.component.BentoSnackbarHost
import dev.bento.designsystem.component.BentoSnackbarHostState
import dev.bento.designsystem.component.BrandLogo
import dev.bento.designsystem.component.FloatingAction
import dev.bento.designsystem.component.FloatingActionBar
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.SectionHeader
import dev.bento.designsystem.component.SegmentOption
import dev.bento.designsystem.component.SegmentedButtons
import dev.bento.designsystem.component.SwitchRow
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.specimen.BentoSpecimens
import dev.bento.designsystem.theme.BentoTheme
import kotlinx.coroutines.launch

/** Debug-only screen showing every primitive, with live sheet/dialog/snackbar/floating-bar demos. */
public class KitchenSinkActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent { KitchenSinkScreen() }
    }
}

private enum class ThemeChoice { System, Light, Dark }

@Composable
public fun KitchenSinkScreen() {
    var theme by rememberSaveable { mutableStateOf(ThemeChoice.System) }
    var reducedMotion by rememberSaveable { mutableStateOf(false) }
    val dark = when (theme) {
        ThemeChoice.System -> isSystemInDarkTheme()
        ThemeChoice.Light -> false
        ThemeChoice.Dark -> true
    }
    BentoTheme(darkTheme = dark, reducedMotion = reducedMotion) {
        val snackbars = remember { BentoSnackbarHostState() }
        val scope = rememberCoroutineScope()
        var sheet by remember { mutableStateOf(false) }
        var dialog by remember { mutableStateOf(false) }
        var selecting by remember { mutableStateOf(false) }

        Box(Modifier.fillMaxSize().background(BentoTheme.colors.tray)) {
            LazyColumn(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.statusBars)) {
                item {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        BrandLogo()
                        SegmentedButtons(
                            listOf(
                                SegmentOption(ThemeChoice.System, "Automático"),
                                SegmentOption(ThemeChoice.Light, "Claro"),
                                SegmentOption(ThemeChoice.Dark, "Oscuro"),
                            ),
                            selected = theme,
                            onSelect = { theme = it },
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    SwitchRow("Reducir movimiento", reducedMotion, { reducedMotion = it })
                    SectionHeader("Demos en vivo")
                    Row(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        BentoButton("Hoja", { sheet = true })
                        BentoButton("Diálogo", { dialog = true })
                        BentoButton("Aviso", {
                            scope.launch { snackbars.showUndo("Se movió a la Papelera", "Deshacer") }
                        })
                        BentoButton("Selección", { selecting = !selecting })
                    }
                }
                items(BentoSpecimens, key = { it.name }) { specimen ->
                    SectionHeader(specimen.name)
                    Box(Modifier.fillMaxWidth().padding(horizontal = 8.dp).background(BentoTheme.colors.surface)) { specimen.content() }
                }
                item { Box(Modifier.padding(64.dp)) }
            }
            Column(Modifier.align(Alignment.BottomCenter).windowInsetsPadding(WindowInsets.navigationBars)) {
                FloatingActionBar(
                    visible = selecting,
                    actions = listOf(
                        FloatingAction(BentoIcons.Share2, "Compartir", {}),
                        FloatingAction(BentoIcons.Trash2, "Eliminar", { selecting = false }, destructive = true),
                    ),
                    onClose = { selecting = false },
                    title = "2 seleccionados",
                )
                BentoSnackbarHost(snackbars)
            }
        }
        if (sheet) {
            BentoSheet(onDismissRequest = { sheet = false }, title = "Cuenta y actividad") {
                ListRow("Todo al día", supporting = "1,2 TB en tu nube · 3 dispositivos")
                ListRow("Ajustes", onClick = { sheet = false })
            }
        }
        if (dialog) {
            BentoDialog(
                title = "¿Quitar este dispositivo?",
                consequence = "Dejará de sincronizar y tendrá que volver a unirse con un código.",
                confirmLabel = "Quitar dispositivo",
                onConfirm = { dialog = false },
                onDismissRequest = { dialog = false },
            )
        }
    }
}

package dev.bento.feature.share

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.feature.files.FolderBrowserState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "es-w411dp-h891dp")
class ShareUiTest {
    @get:Rule
    val compose = createComposeRule()

    private fun body(state: ShareState, actions: ShareActions) =
        compose.setContent { BentoTheme { ShareSheetBody(state, FolderBrowserState(loading = false), actions) } }

    @Test
    fun summaryDestinationAlbumAndSave() {
        val log = mutableListOf<String>()
        body(ShareFixtures.media, ShareActions(onSave = { log += "save" }, onPicker = { log += "picker:$it" }))
        compose.onNodeWithText("3 archivos · 17,2\u00A0MB").assertExists()
        compose.onNodeWithText("Recibos").performClick()
        compose.onNodeWithText("Añadir a álbum").performClick()
        compose.onNode(hasText("Guardar en Bento") and hasClickAction()).performClick()
        assertEquals(listOf("picker:Folder", "picker:Album", "save"), log)
    }

    @Test
    fun unreadableItemsAreNamed() {
        body(ShareFixtures.mixed, ShareActions())
        compose.onNodeWithText("No se puede leer").assertExists()
        compose.onNodeWithText("1 archivo ya no está disponible en la otra app. Lo verás en Actividad.\nRecibo.pdf").assertExists()
        compose.onNodeWithText("Añadir a álbum").assertDoesNotExist()
    }

    @Test
    fun noteAndNothing() {
        var closed = 0
        var state by mutableStateOf(ShareFixtures.note)
        compose.setContent {
            BentoTheme { ShareSheetBody(state, FolderBrowserState(loading = false), ShareActions(onClose = { closed++ })) }
        }
        compose.onNodeWithText("Se guardará como la nota «Lista de compras.txt».").assertExists()
        state = ShareState(loading = false)
        compose.onNodeWithText("No hay nada que Bento pueda guardar de lo que compartiste.").assertExists()
        compose.onNodeWithText("Cerrar").performClick()
        assertEquals(1, closed)
    }

    @Test
    fun savedCannotSaveTwice() {
        body(ShareFixtures.media.copy(saved = true), ShareActions())
        compose.onNode(hasText("Guardar en Bento") and hasClickAction()).assertIsNotEnabled()
    }

    @Test
    fun albumPicker() {
        val picked = mutableListOf<String?>()
        body(
            ShareFixtures.media.copy(picker = SharePicker.Album, albums = listOf(ShareFixtures.album)),
            ShareActions(onAlbum = {
                picked +=
                    it?.id
            })
        )
        compose.onNodeWithText("Cartagena").performClick()
        compose.onNodeWithText("Ninguno").performClick()
        assertEquals(listOf("al1", null), picked)
    }
}

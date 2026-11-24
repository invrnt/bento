package dev.bento.feature.files

import android.content.res.Resources
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext
import dev.bento.data.Undoable

/** Copy decided by a ViewModel, rendered from string resources by the UI (no strings in ViewModels). */
sealed interface UiText {
    data class Res(val id: Int, val args: List<Any> = emptyList()) : UiText

    data class Plural(val id: Int, val count: Int, val args: List<Any> = emptyList()) : UiText

    fun resolve(resources: Resources): String = when (this) {
        is Res -> resources.getString(id, *args.toTypedArray())
        is Plural -> resources.getQuantityString(id, count, *args.toTypedArray())
    }

    companion object {
        fun of(id: Int, vararg args: Any): UiText = Res(id, args.toList())

        fun plural(id: Int, count: Int, vararg args: Any): UiText = Plural(id, count, args.toList())
    }
}

@Composable
fun UiText.text(): String = resolve(LocalContext.current.resources)

/** A calm one-line message; [undo] adds `Deshacer` for 6 s (product/android.md §1.5). */
data class FilesMessage(val text: UiText, val undo: Undoable? = null, val danger: Boolean = false)

/** Whether the phone has a validated network right now (device conditions). */
fun interface Connectivity {
    fun online(): Boolean
}

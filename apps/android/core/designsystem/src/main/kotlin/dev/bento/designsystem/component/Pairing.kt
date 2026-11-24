package dev.bento.designsystem.component

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.generated.BentoTokens
import dev.bento.designsystem.theme.BentoElevation
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.designsystem.theme.bentoShadow
import dev.bento.strings.R as StringsR

/**
 * The short-authentication emojis both devices must show (4 tiles). TalkBack reads one sentence with every emoji in
 * order ("Emojis de verificación: 🐶 🔑 🌵 🎈"), not each tile.
 */
@Composable
public fun SasEmojiRow(
    emojis: List<String>,
    modifier: Modifier = Modifier,
    contentDescription: String = stringResource(StringsR.string.ds_sas_label, emojis.joinToString(" ")),
) {
    val c = BentoTheme.colors
    BoxWithConstraints(modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        val tile = if (maxWidth >= 600.dp) 72.dp else 64.dp
        Row(
            Modifier.clearAndSetSemantics {
                this.contentDescription = contentDescription
                role = Role.Image
            },
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            emojis.forEach { emoji ->
                Box(
                    Modifier
                        .size(tile)
                        .bentoShadow(BentoElevation.Xs, BentoShapes.xl)
                        .clip(BentoShapes.xl)
                        .background(c.subtle)
                        .border(1.dp, c.line, BentoShapes.xl),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(emoji, fontSize = if (tile > 64.dp) 36.sp else 32.sp, textAlign = TextAlign.Center)
                }
            }
        }
    }
}

/** A QR module matrix as produced by the backend (`segno`), row-major, `true` = dark module. */
@Immutable
public class QrMatrix(public val size: Int, private val modules: BooleanArray) {
    init {
        require(modules.size == size * size) { "QrMatrix needs size² modules" }
    }

    public operator fun get(x: Int, y: Int): Boolean = modules[y * size + x]

    public companion object {
        /** Rows of `1`/`#` (dark) and `0`/`.`/space (light). */
        public fun fromRows(rows: List<String>): QrMatrix {
            val size = rows.size
            require(rows.all { it.length == size }) { "QR rows must be square" }
            return QrMatrix(size, BooleanArray(size * size) { i -> rows[i / size][i % size] in "1#" })
        }
    }
}

/**
 * QR code drawn as crisp modules with a 4-module quiet zone. Always dark-on-light (light theme `ink` on white),
 * whatever the theme, because inverted codes are not read by every scanner. Callers set FLAG_SECURE.
 */
@Composable
public fun QrView(
    matrix: QrMatrix,
    modifier: Modifier = Modifier,
    contentDescription: String = stringResource(StringsR.string.ds_qr_label),
) {
    val dark = BentoTokens.LightColors.ink
    val light = BentoTokens.LightColors.white
    Box(
        modifier
            .widthIn(max = 320.dp)
            .aspectRatio(1f)
            .bentoShadow(BentoElevation.Sm, BentoShapes.xl)
            .clip(BentoShapes.xl)
            .background(light)
            .border(1.dp, BentoTheme.colors.line, BentoShapes.xl)
            .clearAndSetSemantics {
                this.contentDescription = contentDescription
                role = Role.Image
            }
            .padding(8.dp),
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val total = matrix.size + QUIET_ZONE * 2
            val cell = this.size.minDimension / total
            for (y in 0 until matrix.size) {
                for (x in 0 until matrix.size) {
                    if (matrix[x, y]) {
                        // Slight overdraw avoids hairline seams between modules at fractional scales.
                        drawRect(dark, Offset((x + QUIET_ZONE) * cell, (y + QUIET_ZONE) * cell), Size(cell + 0.5f, cell + 0.5f))
                    }
                }
            }
        }
    }
}

private const val QUIET_ZONE = 4

/** File kinds of the compartment palette (brand.md §4.5). */
public enum class FileKind { Folder, Pdf, Doc, Sheet, Slides, Image, Video, Audio, Archive, Text }

/** Kind tile: `kind-*` icon on `kind-*-soft`. Decorative unless [contentDescription] is given. */
@Composable
public fun KindIcon(kind: FileKind, modifier: Modifier = Modifier, large: Boolean = false, contentDescription: String? = null) {
    val c = BentoTheme.colors
    val (tint, soft) = when (kind) {
        FileKind.Folder -> c.kindFolder to c.kindFolderSoft
        FileKind.Pdf -> c.kindPdf to c.kindPdfSoft
        FileKind.Doc -> c.kindDoc to c.kindDocSoft
        FileKind.Sheet -> c.kindSheet to c.kindSheetSoft
        FileKind.Slides -> c.kindSlides to c.kindSlidesSoft
        FileKind.Image -> c.kindImage to c.kindImageSoft
        FileKind.Video -> c.kindVideo to c.kindVideoSoft
        FileKind.Audio -> c.kindAudio to c.kindAudioSoft
        FileKind.Archive -> c.kindArchive to c.kindArchiveSoft
        FileKind.Text -> c.kindText to c.kindTextSoft
    }
    val icon = when (kind) {
        FileKind.Folder -> BentoIcons.Folder
        FileKind.Pdf, FileKind.Doc -> BentoIcons.FileText
        FileKind.Sheet -> BentoIcons.FileSpreadsheet
        FileKind.Slides -> BentoIcons.Presentation
        FileKind.Image -> BentoIcons.FileImage
        FileKind.Video -> BentoIcons.FileVideo
        FileKind.Audio -> BentoIcons.FileAudio
        FileKind.Archive -> BentoIcons.FileArchive
        FileKind.Text -> BentoIcons.File
    }
    val size = if (large) 56.dp else 40.dp
    Box(
        modifier
            .size(size)
            .clip(if (large) BentoShapes.lg else BentoShapes.md)
            .background(soft)
            .then(
                if (contentDescription != null) {
                    Modifier.clearAndSetSemantics {
                        this.contentDescription = contentDescription
                        role = Role.Image
                    }
                } else {
                    Modifier.clearAndSetSemantics {}
                },
            ),
        contentAlignment = Alignment.Center,
    ) {
        BentoIcon(icon, contentDescription = null, tint = tint, size = if (large) BentoIconSize.Large else BentoIconSize.Standard)
    }
}

@Composable
public fun fileKindLabel(kind: FileKind): String = stringResource(
    when (kind) {
        FileKind.Folder -> StringsR.string.ds_kind_folder
        FileKind.Pdf -> StringsR.string.ds_kind_pdf
        FileKind.Doc -> StringsR.string.ds_kind_doc
        FileKind.Sheet -> StringsR.string.ds_kind_sheet
        FileKind.Slides -> StringsR.string.ds_kind_slides
        FileKind.Image -> StringsR.string.ds_kind_image
        FileKind.Video -> StringsR.string.ds_kind_video
        FileKind.Audio -> StringsR.string.ds_kind_audio
        FileKind.Archive -> StringsR.string.ds_kind_archive
        FileKind.Text -> StringsR.string.ds_kind_text
    },
)

package dev.bento.designsystem.specimen

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.painter.BrushPainter
import androidx.compose.ui.graphics.painter.Painter
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import dev.bento.designsystem.component.AttentionCard
import dev.bento.designsystem.component.AvatarStatus
import dev.bento.designsystem.component.Badge
import dev.bento.designsystem.component.BadgeSize
import dev.bento.designsystem.component.BentoAnnounce
import dev.bento.designsystem.component.BentoButton
import dev.bento.designsystem.component.BentoButtonSize
import dev.bento.designsystem.component.BentoButtonVariant
import dev.bento.designsystem.component.BentoChip
import dev.bento.designsystem.component.BentoDialogCard
import dev.bento.designsystem.component.BentoFab
import dev.bento.designsystem.component.BentoFavorite
import dev.bento.designsystem.component.BentoFilterChip
import dev.bento.designsystem.component.BentoIcon
import dev.bento.designsystem.component.BentoIconButton
import dev.bento.designsystem.component.BentoIconButtonVariant
import dev.bento.designsystem.component.BentoLoader
import dev.bento.designsystem.component.BentoNavItem
import dev.bento.designsystem.component.BentoNavigationSuite
import dev.bento.designsystem.component.BentoSheetBody
import dev.bento.designsystem.component.BentoSheetHandle
import dev.bento.designsystem.component.BentoSnackbar
import dev.bento.designsystem.component.BentoSnackbarTone
import dev.bento.designsystem.component.BentoTextField
import dev.bento.designsystem.component.BentoTone
import dev.bento.designsystem.component.BentoTopBar
import dev.bento.designsystem.component.BrandLogo
import dev.bento.designsystem.component.BrandMark
import dev.bento.designsystem.component.Callout
import dev.bento.designsystem.component.CalloutTone
import dev.bento.designsystem.component.CodeField
import dev.bento.designsystem.component.CrockfordCode
import dev.bento.designsystem.component.EmptyState
import dev.bento.designsystem.component.ErrorState
import dev.bento.designsystem.component.FileKind
import dev.bento.designsystem.component.FloatingAction
import dev.bento.designsystem.component.FloatingActionBarContent
import dev.bento.designsystem.component.KindIcon
import dev.bento.designsystem.component.ListRow
import dev.bento.designsystem.component.LoadingState
import dev.bento.designsystem.component.NavigationLayout
import dev.bento.designsystem.component.ProgressBar
import dev.bento.designsystem.component.ProgressRing
import dev.bento.designsystem.component.QrMatrix
import dev.bento.designsystem.component.QrView
import dev.bento.designsystem.component.SasEmojiRow
import dev.bento.designsystem.component.SectionHeader
import dev.bento.designsystem.component.SegmentOption
import dev.bento.designsystem.component.SegmentedButtons
import dev.bento.designsystem.component.SettingsRow
import dev.bento.designsystem.component.StatusAvatar
import dev.bento.designsystem.component.StatusDot
import dev.bento.designsystem.component.SwitchRow
import dev.bento.designsystem.component.Thumbnail
import dev.bento.designsystem.component.VideoBadge
import dev.bento.designsystem.component.bentoSnackbarPreviewData
import dev.bento.designsystem.component.fileKindLabel
import dev.bento.designsystem.generated.BentoIconCatalog
import dev.bento.designsystem.generated.BentoIcons
import dev.bento.designsystem.generated.BentoNavIcons
import dev.bento.designsystem.theme.BentoShapes
import dev.bento.designsystem.theme.BentoTheme
import dev.bento.strings.R as StringsR

/** A named primitive state group, shared by previews, the kitchen sink and the Roborazzi suite. */
public class Specimen(public val name: String, public val content: @Composable () -> Unit) {
    override fun toString(): String = name
}

@Composable
private fun Group(content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) { content() }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Flow(content: @Composable () -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) { content() }
}

/** A photo-like painter from kind tokens, so screenshots need no image files. */
@Composable
internal fun samplePhotoBrush(seed: Int = 0): Brush {
    val c = BentoTheme.colors
    val pairs = listOf(c.kindVideo to c.kindSheet, c.kindFolder to c.kindSlides, c.kindImage to c.kindDoc, c.kindSheet to c.kindFolder)
    val (a, b) = pairs[seed % pairs.size]
    return Brush.linearGradient(listOf(a, b))
}

@Composable
internal fun samplePhoto(seed: Int = 0): Painter = BrushPainter(samplePhotoBrush(seed))

internal val sampleQr: QrMatrix = QrMatrix.fromRows(
    listOf(
        "111111101011101111111",
        "100000101100101000001",
        "101110100111001011101",
        "101110101010101011101",
        "101110100101101011101",
        "100000101110001000001",
        "111111101010101111111",
        "000000001101100000000",
        "110110111011011011011",
        "010011010110100110100",
        "101101101001011101101",
        "011010010110110010010",
        "110101111010101101011",
        "000000001011001001010",
        "111111100110110110101",
        "100000101011011010010",
        "101110101101100101101",
        "101110100010110110010",
        "101110101101011011101",
        "100000100110101100010",
        "111111101011010110101"
    )
)

@Composable
private fun navItems(): List<BentoNavItem> = listOf(
    BentoNavItem("photos", "Fotos", BentoNavIcons.Images),
    BentoNavItem("files", "Archivos", BentoNavIcons.FolderClosed),
    BentoNavItem("collections", "Colecciones", BentoNavIcons.SquareLibrary)
)

@Composable
private fun Placeholder(height: Int) {
    Box(
        Modifier
            .fillMaxWidth()
            .height(height.dp)
            .padding(8.dp)
            .clip(BentoShapes.xl)
            .background(BentoTheme.colors.surface)
    )
}

/** Every primitive of design-system/android.md §8 with its states. */
public val BentoSpecimens: List<Specimen> = listOf(
    Specimen("brand") {
        Group {
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.CenterVertically) {
                BrandMark(size = 16.dp)
                BrandMark(size = 28.dp)
                BrandMark(size = 48.dp, contentDescription = "Bento")
                BrandLogo()
                BrandLogo(markSize = 40.dp)
            }
        }
    },
    Specimen("loader") {
        Group {
            Row(horizontalArrangement = Arrangement.spacedBy(24.dp), verticalAlignment = Alignment.CenterVertically) {
                BentoLoader()
                BentoLoader(size = 56.dp)
            }
            LoadingState()
        }
    },
    Specimen("top-bar") {
        Column(Modifier.background(BentoTheme.colors.tray)) {
            BentoTopBar(
                stringResource(StringsR.string.common_action_search_bento),
                onSearchClick = {},
                windowInsets = androidx.compose.foundation.layout.WindowInsets(0)
            ) { StatusAvatar("Ana Pérez", AvatarStatus.Syncing, onClick = {}, progress = 0.42f) }
            BentoTopBar(
                stringResource(StringsR.string.common_action_search_bento),
                onSearchClick = {},
                windowInsets = androidx.compose.foundation.layout.WindowInsets(0)
            ) { StatusAvatar("Ana Pérez", AvatarStatus.Idle, onClick = {}) }
        }
    },
    Specimen("status-avatar") {
        Group {
            Flow {
                AvatarStatus.entries.forEach { StatusAvatar("Ana Pérez", it, onClick = {}) }
                StatusAvatar("Ana Pérez", AvatarStatus.Syncing, onClick = {}, progress = 0.7f)
                StatusAvatar("Luis", AvatarStatus.Idle, onClick = {}, image = samplePhoto(1))
            }
        }
    },
    Specimen("navigation-bar") {
        Box(Modifier.height(200.dp)) {
            BentoNavigationSuite(navItems(), "photos", {}, layout = NavigationLayout.Bar) { Placeholder(120) }
        }
    },
    Specimen("navigation-rail") {
        Box(Modifier.height(360.dp)) {
            BentoNavigationSuite(
                navItems(),
                "files",
                {},
                layout = NavigationLayout.Rail,
                railHeader = { BrandMark(size = 32.dp) }
            ) { Placeholder(360) }
        }
    },
    Specimen("button-variants") {
        Group {
            BentoButtonVariant.entries.forEach { v ->
                BentoButton(
                    when (v) {
                        BentoButtonVariant.Primary -> "Subir archivos"
                        BentoButtonVariant.Secondary -> "Crear álbum"
                        BentoButtonVariant.Ghost -> "Ahora no"
                        BentoButtonVariant.Danger -> "Eliminar para siempre"
                        BentoButtonVariant.DangerGhost -> "Quitar dispositivo"
                    },
                    onClick = {},
                    variant = v,
                    leadingIcon = if (v == BentoButtonVariant.Primary) BentoIcons.Upload else null
                )
            }
        }
    },
    Specimen("button-states") {
        Group {
            Flow {
                BentoButtonSize.entries.forEach { BentoButton("Guardar", {}, variant = BentoButtonVariant.Primary, size = it) }
            }
            Flow {
                BentoButton("Subiendo…", {}, variant = BentoButtonVariant.Primary, loading = true)
                BentoButton("Reintentar", {}, leadingIcon = BentoIcons.RotateCw)
                BentoButton("Continuar", {}, trailingIcon = BentoIcons.ChevronRight, variant = BentoButtonVariant.Primary, enabled = false)
            }
            BentoButton("Liberar espacio en el teléfono", {
            }, Modifier.fillMaxWidth(), variant = BentoButtonVariant.Primary, size = BentoButtonSize.Large)
        }
    },
    Specimen("icon-button") {
        Group {
            Flow {
                BentoIconButton(BentoIcons.Share2, "Compartir", {})
                BentoIconButton(BentoIcons.Download, "Descargar al teléfono", {}, variant = BentoIconButtonVariant.Secondary)
                BentoIconButton(BentoIcons.Plus, "Nuevo", {}, variant = BentoIconButtonVariant.Accent)
                BentoIconButton(BentoIcons.LayoutGrid, "Vista de cuadrícula", {}, selected = true)
                BentoIconButton(BentoIcons.EllipsisVertical, "Más opciones", {}, dense = true)
                BentoIconButton(BentoIcons.Trash2, "Eliminar", {}, enabled = false)
            }
            Box(Modifier.clip(BentoShapes.lg).background(samplePhotoBrush(2)).padding(8.dp)) {
                Row {
                    BentoIconButton(BentoIcons.ArrowLeft, "Atrás", {}, variant = BentoIconButtonVariant.Overlay)
                    BentoIconButton(BentoIcons.Share2, "Compartir", {}, variant = BentoIconButtonVariant.Overlay)
                }
            }
        }
    },
    Specimen("fab") {
        Group {
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                BentoFab(stringResource(StringsR.string.common_action_new), BentoIcons.Plus, {})
                BentoFab(stringResource(StringsR.string.common_action_new), BentoIcons.Plus, {}, expanded = false)
            }
        }
    },
    Specimen("text-field") {
        Group {
            BentoTextField(rememberTextFieldState(), "Nombre del álbum", placeholder = "Viaje a Cartagena")
            BentoTextField(rememberTextFieldState("Vacaciones 2024"), "Nombre del álbum", hint = "Puedes cambiarlo después.")
            BentoTextField(rememberTextFieldState("ana@"), "Correo", error = "Escribe un correo completo.", leadingIcon = BentoIcons.User)
            BentoTextField(
                rememberTextFieldState("contraseña"),
                "Contraseña de Telegram",
                secure = true,
                hint = "La de verificación en dos pasos."
            )
            BentoTextField(rememberTextFieldState("Solo lectura"), "Carpeta", enabled = false)
        }
    },
    Specimen("code-field") {
        Group {
            CodeField(rememberTextFieldState(), "Código de vinculación", hint = "Lo ves en el computador, en Añadir dispositivo.")
            CodeField(rememberTextFieldState("7KQ2M9"), "Código de vinculación")
            CodeField(rememberTextFieldState("7KQ2M9XWD4PH"), "Código de vinculación")
            CodeField(
                rememberTextFieldState("7KQ2M9XWD4PA"),
                "Código de vinculación",
                error = "El código no coincide. Revísalo en el computador."
            )
            CodeField(
                rememberTextFieldState("ABCD1234EFGH5678JKMN9012PQRS3456TVWX"),
                "Código de recuperación",
                length = CrockfordCode.RECOVERY_LENGTH
            )
        }
    },
    Specimen("segmented") {
        Group {
            SegmentedButtons(
                listOf(SegmentOption("auto", "Automático"), SegmentOption("light", "Claro"), SegmentOption("dark", "Oscuro")),
                selected = "light",
                onSelect = {},
                modifier = Modifier.fillMaxWidth()
            )
            SegmentedButtons(
                listOf(SegmentOption("grid", "Cuadrícula", BentoIcons.LayoutGrid), SegmentOption("list", "Lista", BentoIcons.List)),
                selected = "grid",
                onSelect = {},
                iconOnly = true,
                modifier = Modifier.width(128.dp)
            )
        }
    },
    Specimen("chips") {
        Group {
            Flow {
                BentoChip("Tipo", {}, trailingIcon = BentoIcons.ChevronDown)
                BentoFilterChip("Fotos", selected = true, onSelectedChange = {})
                BentoFilterChip("Videos", selected = false, onSelectedChange = {})
                BentoFilterChip("Documentos", selected = false, onSelectedChange = {}, leadingIcon = BentoIcons.FileText)
                BentoChip("Este teléfono", {}, leadingIcon = BentoIcons.Smartphone, enabled = false)
            }
        }
    },
    Specimen("sheet") {
        Column(Modifier.fillMaxWidth().background(BentoTheme.colors.scrim).padding(top = 48.dp)) {
            Column(Modifier.fillMaxWidth().clip(BentoShapes.sheet).background(BentoTheme.colors.raised)) {
                BentoSheetHandle()
                BentoSheetBody("Cuenta y actividad") {
                    ListRow("Todo al día", supporting = "1,2 TB en tu nube · 3 dispositivos", leading = {
                        StatusAvatar("Ana Pérez", AvatarStatus.Idle, {})
                    })
                    SettingsRow("Dispositivos", {}, icon = BentoIcons.Smartphone, value = "3")
                    SettingsRow("Ajustes", {}, icon = BentoIcons.Settings2)
                }
            }
        }
    },
    Specimen("dialog") {
        Box(Modifier.fillMaxWidth().background(BentoTheme.colors.scrim).padding(24.dp), contentAlignment = Alignment.Center) {
            BentoDialogCard(
                title = "¿Eliminar para siempre 3 archivos?",
                consequence = "Se borrarán de tu nube y de todos tus dispositivos. No se puede deshacer.",
                confirmLabel = "Eliminar para siempre",
                onConfirm = {},
                dismissLabel = stringResource(StringsR.string.common_action_cancel),
                onDismiss = {},
                icon = BentoIcons.Trash2
            )
        }
    },
    Specimen("callout") {
        Group {
            Callout(tone = CalloutTone.Neutral, body = "Las miniaturas se crean en segundo plano.")
            Callout(tone = CalloutTone.Info, title = "Respaldo activado", body = "Bento guarda tus fotos nuevas en tu nube.")
            Callout(tone = CalloutTone.Success, title = "Todo al día", body = "Tus 3 dispositivos están sincronizados.")
            Callout(
                tone = CalloutTone.Warning,
                title = "Telegram pidió esperar",
                body = stringResource(StringsR.string.common_error_flood_wait, "4 min"),
                announce = BentoAnnounce.Polite
            ) { BentoButton("Ver actividad", {}, size = BentoButtonSize.Small) }
            Callout(
                tone = CalloutTone.Danger,
                title = stringResource(StringsR.string.common_error_session_revoked),
                body = "Tu biblioteca sigue visible."
            ) {
                BentoButton(stringResource(StringsR.string.common_action_reconnect), {
                }, size = BentoButtonSize.Small, variant = BentoButtonVariant.Primary)
            }
        }
    },
    Specimen("attention-card") {
        Group {
            AttentionCard("Hay una versión nueva", "Bento 1.2 trae mejoras de respaldo.", "Actualizar", {
            }, icon = BentoIcons.Download, onDismiss = {})
            AttentionCard(
                "El teléfono no tiene espacio",
                "Pausamos el respaldo hasta que haya espacio.",
                stringResource(StringsR.string.common_action_free_space),
                {},
                tone = CalloutTone.Warning
            )
        }
    },
    Specimen("badge") {
        Group {
            Flow {
                Badge("Neutral")
                Badge("Indexado", tone = BentoTone.Success, dot = true)
                Badge("Subiendo", tone = BentoTone.Accent, dot = true, pulse = true)
                Badge("Pendiente", tone = BentoTone.Warning, icon = BentoIcons.CloudUpload)
                Badge("Falló", tone = BentoTone.Danger, size = BadgeSize.Medium)
                Badge("Recomendado", tone = BentoTone.Shu)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
                BentoTone.entries.filter { it != BentoTone.Shu }.forEach { StatusDot(tone = it) }
                Text("Estados", color = BentoTheme.colors.inkMuted, style = BentoTheme.typography.metadata)
            }
        }
    },
    Specimen("progress") {
        Group {
            ProgressBar(0.42f, label = "Subiendo 3 archivos")
            ProgressBar(1f, tone = BentoTone.Success, label = "Listo")
            ProgressBar(null, label = "Preparando")
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.CenterVertically) {
                ProgressRing(0.25f, trackColor = BentoTheme.colors.sunken, label = "Respaldo")
                ProgressRing(0.75f, size = 40.dp, trackColor = BentoTheme.colors.sunken, label = "Respaldo")
                ProgressRing(null, label = "Cargando")
            }
        }
    },
    Specimen("empty-state") {
        Group {
            EmptyState("Aún no hay archivos", "Sube archivos o crea carpetas.") {
                BentoButton("Subir archivos", {}, variant = BentoButtonVariant.Primary, leadingIcon = BentoIcons.Upload)
            }
            EmptyState("No encontramos nada", "Prueba con otras palabras.", icon = BentoIcons.Search, compact = true)
        }
    },
    Specimen("error-state") {
        Group {
            ErrorState(stringResource(StringsR.string.common_error_generic), onRetry = {})
            ErrorState(stringResource(StringsR.string.common_error_network), title = "Sin conexión")
        }
    },
    Specimen("thumbnail") {
        Group {
            Row(horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                Thumbnail(null, "Foto, pendiente", Modifier.size(96.dp))
                Thumbnail(samplePhoto(0), "Foto", Modifier.size(96.dp)) {
                    BentoFavorite(true, Modifier.align(Alignment.BottomStart).padding(6.dp), size = 16.dp)
                }
                Thumbnail(samplePhoto(1), "Video", Modifier.size(96.dp)) {
                    VideoBadge("0:42", Modifier.align(Alignment.TopEnd).padding(6.dp))
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                Thumbnail(samplePhoto(2), "Foto, seleccionada", Modifier.size(96.dp), selected = true, selectionMode = true)
                Thumbnail(samplePhoto(3), "Foto", Modifier.size(96.dp), selectionMode = true)
                Thumbnail(samplePhoto(0), "Panorámica", Modifier.width(194.dp), aspectRatio = 2f)
            }
        }
    },
    Specimen("floating-action-bar") {
        Box(Modifier.fillMaxWidth().background(BentoTheme.colors.tray).padding(vertical = 8.dp)) {
            FloatingActionBarContent(
                actions = listOf(
                    FloatingAction(BentoIcons.Share2, "Compartir", {}),
                    FloatingAction(BentoIcons.ImagePlus, "Añadir a álbum", {}),
                    FloatingAction(BentoIcons.Heart, "Favorito", {}),
                    FloatingAction(BentoIcons.Trash2, "Eliminar", {}, destructive = true)
                ),
                onClose = {},
                title = pluralStringResource(StringsR.plurals.common_count_selected, 12, "12"),
                overflow = listOf(FloatingAction(BentoIcons.Send, "Enviar por Telegram…", {})),
                closeLabel = "Cancelar selección"
            )
        }
    },
    Specimen("snackbar") {
        Group {
            BentoSnackbar(bentoSnackbarPreviewData("Se movió a la Papelera", stringResource(StringsR.string.common_action_undo)))
            BentoSnackbar(bentoSnackbarPreviewData("Álbum creado", null, BentoSnackbarTone.Success))
            BentoSnackbar(
                bentoSnackbarPreviewData(
                    stringResource(StringsR.string.common_error_generic),
                    stringResource(StringsR.string.common_action_retry),
                    BentoSnackbarTone.Danger
                )
            )
        }
    },
    Specimen("sas-emoji") {
        Group { SasEmojiRow(listOf("🐶", "🔑", "🌵", "🎈")) }
    },
    Specimen("qr") {
        Group { QrView(sampleQr, Modifier.size(200.dp)) }
    },
    Specimen("kind-icon") {
        Group {
            Flow { FileKind.entries.forEach { KindIcon(it) } }
            Flow { FileKind.entries.take(5).forEach { KindIcon(it, large = true, contentDescription = fileKindLabel(it)) } }
        }
    },
    Specimen("list-row") {
        Column(Modifier.fillMaxWidth().background(BentoTheme.colors.surface)) {
            ListRow("Facturas", supporting = "12 archivos · hace 2 días", leading = { KindIcon(FileKind.Folder) }, onClick = {})
            ListRow("contrato-arriendo.pdf", supporting = "1,5 MB", leading = { KindIcon(FileKind.Pdf) }, trailing = {
                BentoIconButton(BentoIcons.EllipsisVertical, "Más opciones", {}, dense = true)
            }, onClick = {})
            ListRow("presupuesto.xlsx", supporting = "Seleccionado", leading = { KindIcon(FileKind.Sheet) }, selected = true, onClick = {})
            ListRow("Sin conexión", leading = { BentoIcon(BentoIcons.CloudOff, null, tint = BentoTheme.colors.inkMuted) }, enabled = false)
        }
    },
    Specimen("section-header") {
        Column(Modifier.fillMaxWidth()) {
            SectionHeader("Álbumes", actionLabel = "Ver todo", onAction = {})
            SectionHeader("Del teléfono")
        }
    },
    Specimen("settings-row") {
        Column(Modifier.fillMaxWidth().background(BentoTheme.colors.surface)) {
            SettingsRow("Idioma", {}, icon = BentoIcons.Settings2, value = "Español")
            SettingsRow("Dispositivos", {}, summary = "3 dispositivos en tu nube", icon = BentoIcons.Smartphone)
            SwitchRow("Respaldo del teléfono", checked = true, onCheckedChange = {
            }, summary = "Solo con Wi-Fi", icon = BentoIcons.CloudUpload)
            SwitchRow("Bloqueo de la app", checked = false, onCheckedChange = {}, icon = BentoIcons.Lock)
            SwitchRow("Usar datos móviles", checked = false, onCheckedChange = {}, enabled = false)
        }
    },
    Specimen("icons") {
        Group {
            Flow {
                BentoIconCatalog.forEach { (name, icon) -> BentoIcon(icon, name, tint = BentoTheme.colors.ink, size = 24.dp) }
            }
        }
    },
    Specimen("typography") {
        val t = BentoTheme.typography
        Group {
            Text("1.248 fotos", style = t.hero)
            Text("Archivos", style = t.pageTitle)
            Text("Marzo de 2024", style = t.monthHeader)
            Text("Cuenta y actividad", style = t.sectionTitle)
            Text("Tu nube privada, en orden. Todo en su lugar.", style = t.body)
            Text("Subir archivos", style = t.label)
            Text("1,5 MB · hace 2 días", style = t.metadata, color = BentoTheme.colors.inkMuted)
            Text("7KQ2-M9XW-D4PH", style = t.monoLarge)
        }
    },
    Specimen("palette") {
        val c = BentoTheme.colors
        val swatches = listOf(
            "tray" to c.tray, "surface" to c.surface, "raised" to c.raised, "subtle" to c.subtle, "sunken" to c.sunken,
            "ink" to c.ink, "ink-muted" to c.inkMuted, "ink-subtle" to c.inkSubtle, "accent" to c.accent, "accent-soft" to c.accentSoft,
            "accent-ink" to c.accentInk, "shu" to c.shu, "success" to c.success, "warning" to c.warning, "danger" to c.danger
        )
        Group {
            Flow {
                swatches.forEach { (name, color) ->
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Box(Modifier.size(48.dp).clip(BentoShapes.md).background(color).then(Modifier))
                        Text(name, style = BentoTheme.typography.caption, color = c.inkMuted)
                    }
                }
            }
        }
    }
)

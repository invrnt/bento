package dev.bento.feature.settings

import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import dev.bento.designsystem.component.ListRow
import dev.bento.strings.R as StringsR

/** An open-source component shipped in the APK and its license (names are proper nouns, not translated). */
data class OssComponent(val name: String, val license: String)

/**
 * Ajustes › Acerca de › Licencias de código abierto. Hand-kept list of what the APK ships (Kotlin/Android side and the
 * embedded Python backend); no Play-services license plugin (product/android.md §1.7). Stage 22 may generate it.
 */
object OssLicenses {
    val components: List<OssComponent> = listOf(
        OssComponent("AndroidX, Jetpack Compose, Material 3", "Apache License 2.0"),
        OssComponent("Kotlin, kotlinx.coroutines, kotlinx.serialization", "Apache License 2.0"),
        OssComponent("Dagger / Hilt", "Apache License 2.0"),
        OssComponent("OkHttp", "Apache License 2.0"),
        OssComponent("Coil", "Apache License 2.0"),
        OssComponent("AndroidX Media3", "Apache License 2.0"),
        OssComponent("ML Kit (text recognition, document scanner)", "ML Kit Terms of Service"),
        OssComponent("Chaquopy", "MIT License"),
        OssComponent("Python", "Python Software Foundation License"),
        OssComponent("Telethon", "MIT License"),
        OssComponent("cryptg", "CC0 1.0"),
        OssComponent("FastAPI, Starlette", "MIT License / BSD 3-Clause"),
        OssComponent("Pydantic", "MIT License"),
        OssComponent("SQLAlchemy, Alembic", "MIT License"),
        OssComponent("Uvicorn", "BSD 3-Clause"),
        OssComponent("cryptography", "Apache License 2.0 / BSD 3-Clause"),
        OssComponent("spake2", "MIT License"),
        OssComponent("segno", "BSD 3-Clause"),
        OssComponent("Pillow", "MIT-CMU (HPND)"),
        OssComponent("Geist, Geist Mono", "SIL Open Font License 1.1"),
        OssComponent("Lucide icons", "ISC License")
    )
}

@Composable
fun LicensesPage(onBack: (() -> Unit)?) {
    SettingsPage(stringResource(StringsR.string.settings_licenses), onBack) {
        SettingsGroup {
            OssLicenses.components.forEach { ListRow(headline = it.name, supporting = it.license) }
        }
    }
}

package dev.bento.designsystem.lint

import com.android.tools.lint.checks.infrastructure.LintDetectorTest
import com.android.tools.lint.checks.infrastructure.TestFile
import com.android.tools.lint.detector.api.Detector
import com.android.tools.lint.detector.api.Issue

class BentoDetectorsTest : LintDetectorTest() {
    override fun getDetector(): Detector = BentoDetectors.Scanner()

    override fun getIssues(): List<Issue> = BentoIssueRegistry().issues

    private val stubs: Array<TestFile> = arrayOf(
        kotlin(
            """
            package androidx.compose.runtime
            annotation class Composable
            """,
        ).indented(),
        kotlin(
            """
            package androidx.compose.ui.graphics
            @JvmInline value class Color(val value: ULong) {
                companion object {
                    val Red: Color = Color(0u)
                    val Black: Color = Color(0u)
                    val Transparent: Color = Color(0u)
                }
            }
            fun Color(color: Long): Color = Color(color.toULong())
            """,
        ).indented(),
        kotlin(
            """
            package androidx.compose.material3
            import androidx.compose.runtime.Composable
            import androidx.compose.ui.graphics.Color
            class ColorScheme(val primary: Color)
            object MaterialTheme { val colorScheme: ColorScheme get() = ColorScheme(Color.Transparent) }
            @Composable fun Text(text: String, color: Color = Color.Transparent) {}
            """,
        ).indented(),
        kotlin(
            """
            package androidx.compose.animation.core
            import androidx.compose.runtime.Composable
            @Composable fun animateFloatAsState(targetValue: Float, label: String = ""): Float = targetValue
            """,
        ).indented(),
        kotlin(
            """
            package androidx.compose.ui.tooling.preview
            annotation class Preview
            """,
        ).indented(),
    )

    fun testRawColorsAreFlaggedInFeatureCode() {
        lint().files(
            *stubs,
            kotlin(
                """
                package dev.bento.feature.photos
                import androidx.compose.ui.graphics.Color
                val accent = Color(0xFF3857D8)
                val alarm = Color.Red
                val none = Color.Transparent
                """,
            ).indented(),
        ).allowMissingSdk().run().expectErrorCount(2).expectContains("BentoNoRawColor")
    }

    fun testTokenOwnersMayHoldRawColors() {
        lint().files(
            *stubs,
            kotlin(
                """
                package dev.bento.designsystem.generated
                import androidx.compose.ui.graphics.Color
                val tray = Color(0xFFF5F2EE)
                val paint = Color.Black
                """,
            ).indented(),
        ).allowMissingSdk().run().expectClean()
    }

    fun testMaterialColorSchemeIsFlaggedOutsideTheDesignSystem() {
        lint().files(
            *stubs,
            kotlin(
                """
                package dev.bento.feature.files
                import androidx.compose.material3.MaterialTheme
                val primary = MaterialTheme.colorScheme.primary
                """,
            ).indented(),
        ).allowMissingSdk().run().expectErrorCount(1).expectContains("BentoMaterialColorScheme")
    }

    fun testHardcodedComposeTextIsFlagged() {
        lint().files(
            *stubs,
            kotlin(
                """
                package dev.bento.feature.files
                import androidx.compose.material3.Text
                import androidx.compose.runtime.Composable
                import androidx.compose.ui.tooling.preview.Preview
                @Composable fun Screen(name: String) {
                    androidx.compose.animation.core.animateFloatAsState(1f, label = "fade")
                    Text("Subir archivos")
                    Text(text = "Hola, ${'$'}name")
                    Text(name)
                    Text("·")
                }
                @Preview @Composable fun ScreenPreview() { Text("Vista previa") }
                """,
            ).indented(),
        ).allowMissingSdk().run().expectErrorCount(2).expectContains("BentoHardcodedText")
    }
}

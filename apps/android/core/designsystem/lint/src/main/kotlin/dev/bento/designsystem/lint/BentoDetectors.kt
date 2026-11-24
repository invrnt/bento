package dev.bento.designsystem.lint

import com.android.tools.lint.detector.api.Category
import com.android.tools.lint.detector.api.Detector
import com.android.tools.lint.detector.api.Implementation
import com.android.tools.lint.detector.api.Issue
import com.android.tools.lint.detector.api.JavaContext
import com.android.tools.lint.detector.api.Scope
import com.android.tools.lint.detector.api.Severity
import com.android.tools.lint.detector.api.SourceCodeScanner
import com.intellij.psi.PsiField
import com.intellij.psi.PsiMethod
import org.jetbrains.uast.UCallExpression
import org.jetbrains.uast.UElement
import org.jetbrains.uast.ULiteralExpression
import org.jetbrains.uast.UMethod
import org.jetbrains.uast.UPolyadicExpression
import org.jetbrains.uast.USimpleNameReferenceExpression
import org.jetbrains.uast.UQualifiedReferenceExpression
import org.jetbrains.uast.UReferenceExpression
import org.jetbrains.uast.getContainingUFile
import org.jetbrains.uast.getParentOfType

/** The design system itself (theme + generated tokens) is the only place allowed to hold raw colors. */
private fun JavaContext.isTokenOwner(element: UElement): Boolean {
    val pkg = element.getContainingUFile()?.packageName ?: return false
    return pkg.startsWith("dev.bento.designsystem.generated") || pkg.startsWith("dev.bento.designsystem.theme")
}

private fun UElement.inPreview(): Boolean {
    var method = getParentOfType(UMethod::class.java)
    while (method != null) {
        if (method.uAnnotations.any { it.qualifiedName?.endsWith("Preview") == true || it.qualifiedName?.endsWith("Previews") == true }) return true
        method = method.getParentOfType(UMethod::class.java)
    }
    return false
}

object BentoDetectors {
    private val implementation = Implementation(Scanner::class.java, Scope.JAVA_FILE_SCOPE)

    @JvmField
    val RAW_COLOR: Issue = Issue.create(
        id = "BentoNoRawColor",
        briefDescription = "Raw color instead of a Bento token",
        explanation = "Colors come only from `BentoTheme.colors` (generated from tokens.css). Hex literals, `Color(0x…)`, " +
            "`Color.Red`-style constants and `parseColor` break light/dark and the brand palette.",
        category = Category.CORRECTNESS,
        priority = 7,
        severity = Severity.ERROR,
        implementation = implementation,
    )

    @JvmField
    val MATERIAL_COLOR_SCHEME: Issue = Issue.create(
        id = "BentoMaterialColorScheme",
        briefDescription = "MaterialTheme.colorScheme outside the design system",
        explanation = "Material roles are an implementation detail of `BentoTheme`. Read colors from `BentoTheme.colors` " +
            "so every surface uses the Bento role it means (tray, raised, accent-ink…).",
        category = Category.CORRECTNESS,
        priority = 6,
        severity = Severity.ERROR,
        implementation = implementation,
    )

    @JvmField
    val HARDCODED_TEXT: Issue = Issue.create(
        id = "BentoHardcodedText",
        briefDescription = "Hardcoded user-facing text in Compose",
        explanation = "User-facing strings live in `core/strings` (Spanish default, English mirror). Use `stringResource` " +
            "or `pluralStringResource` instead of a literal.",
        category = Category.I18N,
        priority = 6,
        severity = Severity.ERROR,
        implementation = implementation,
    )

    /** Composable parameters that carry user-facing text. */
    internal val textParameters = setOf(
        "text", "label", "title", "body", "message", "hint", "placeholder", "contentDescription", "consequence",
        "confirmLabel", "dismissLabel", "actionLabel", "searchLabel", "loadingLabel", "closeLabel", "retryLabel",
        "headline", "supporting", "summary", "value",
    )

    internal val colorConstants = setOf(
        "Black", "DarkGray", "Gray", "LightGray", "White", "Red", "Green", "Blue", "Yellow", "Cyan", "Magenta",
    )

    class Scanner : Detector(), SourceCodeScanner {
        override fun getApplicableMethodNames(): List<String> = listOf("Color", "parseColor")

        override fun getApplicableReferenceNames(): List<String> = colorConstants.toList() + "colorScheme"

        override fun getApplicableUastTypes(): List<Class<out UElement>> = listOf(UCallExpression::class.java)

        override fun visitMethodCall(context: JavaContext, node: UCallExpression, method: PsiMethod) {
            if (context.isTokenOwner(node)) return
            val owner = method.containingClass?.qualifiedName.orEmpty()
            val isComposeColor = method.name == "Color" && owner.startsWith("androidx.compose.ui.graphics")
            val isParse = method.name == "parseColor" && owner == "android.graphics.Color"
            if (isComposeColor || isParse) {
                context.report(RAW_COLOR, node, context.getLocation(node), "Use a `BentoTheme.colors` token instead of a raw color")
            }
        }

        override fun visitReference(context: JavaContext, reference: UReferenceExpression, referenced: com.intellij.psi.PsiElement) {
            val name = (reference as? USimpleNameReferenceExpression)?.identifier ?: return
            if (name == "colorScheme") {
                val owner = (referenced as? PsiMethod)?.containingClass?.qualifiedName ?: (referenced as? PsiField)?.containingClass?.qualifiedName
                val pkg = reference.getContainingUFile()?.packageName.orEmpty()
                if (owner == "androidx.compose.material3.MaterialTheme" && !pkg.startsWith("dev.bento.designsystem")) {
                    context.report(MATERIAL_COLOR_SCHEME, reference, context.getLocation(reference), "Use `BentoTheme.colors` instead of `MaterialTheme.colorScheme`")
                }
                return
            }
            if (context.isTokenOwner(reference)) return
            val owner = when (referenced) {
                is PsiMethod -> referenced.containingClass?.qualifiedName
                is PsiField -> referenced.containingClass?.qualifiedName
                else -> null
            }.orEmpty()
            if (owner.startsWith("androidx.compose.ui.graphics.Color") || owner == "android.graphics.Color") {
                context.report(RAW_COLOR, reference, context.getLocation(reference), "Use a `BentoTheme.colors` token instead of `Color.$name`")
            }
        }

        override fun createUastHandler(context: JavaContext) = object : com.android.tools.lint.client.api.UElementHandler() {
            override fun visitCallExpression(node: UCallExpression) {
                val method = node.resolve() ?: return
                val composable = method.annotations.any { it.qualifiedName == "androidx.compose.runtime.Composable" }
                if (!composable || node.inPreview()) return
                // `label` on animation APIs names the animation for tooling; it is never shown to people.
                if (method.containingClass?.qualifiedName.orEmpty().startsWith("androidx.compose.animation")) return
                val pkg = node.getContainingUFile()?.packageName.orEmpty()
                if (pkg.contains(".specimen") || pkg.contains(".kitchensink")) return
                val mapping = context.evaluator.computeArgumentMapping(node, method)
                for ((argument, parameter) in mapping) {
                    if (parameter.name !in textParameters) continue
                    if (isUserText(argument)) {
                        context.report(
                            HARDCODED_TEXT,
                            argument,
                            context.getLocation(argument),
                            "Move \"${argument.asSourceString().trim('"')}\" to core/strings and use `stringResource`",
                        )
                    }
                }
            }
        }

        private fun isUserText(element: UElement): Boolean = when (element) {
            is ULiteralExpression -> (element.value as? String)?.any { it.isLetter() } == true
            is UPolyadicExpression -> element.operands.any { it is ULiteralExpression && (it.value as? String)?.any { c -> c.isLetter() } == true }
            is UQualifiedReferenceExpression -> false
            else -> false
        }
    }
}

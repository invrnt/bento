package dev.bento.designsystem.lint

import com.android.tools.lint.client.api.IssueRegistry
import com.android.tools.lint.client.api.Vendor
import com.android.tools.lint.detector.api.CURRENT_API
import com.android.tools.lint.detector.api.Issue

/** Lint rules that keep feature code on Bento tokens and strings (design-system/android.md §1, AGENTS.md i18n). */
class BentoIssueRegistry : IssueRegistry() {
    override val issues: List<Issue> = listOf(
        BentoDetectors.RAW_COLOR,
        BentoDetectors.MATERIAL_COLOR_SCHEME,
        BentoDetectors.HARDCODED_TEXT,
    )
    override val api: Int = CURRENT_API
    override val minApi: Int = 12
    override val vendor: Vendor = Vendor(vendorName = "Bento", identifier = "dev.bento.designsystem")
}

package dev.bento.buildlogic

import com.android.build.api.dsl.CommonExtension
import org.gradle.api.JavaVersion
import org.gradle.api.Project
import org.gradle.api.artifacts.VersionCatalog
import org.gradle.api.artifacts.VersionCatalogsExtension
import org.gradle.api.tasks.testing.Test
import org.gradle.kotlin.dsl.getByType
import org.gradle.kotlin.dsl.withType

internal val Project.libs: VersionCatalog
    get() = extensions.getByType<VersionCatalogsExtension>().named("libs")

internal fun VersionCatalog.version(alias: String): String = findVersion(alias).get().requiredVersion

internal fun VersionCatalog.lib(alias: String): Any = findLibrary(alias).get().get()

/** Settings shared by every Android module (application, library, test). */
internal fun Project.configureAndroidCommon(extension: CommonExtension) {
    extension.compileSdk = libs.version("compileSdk").toInt()
    extension.compileSdkMinor = libs.version("compileSdkMinor").toInt()
    extension.defaultConfig.minSdk = libs.version("minSdk").toInt()
    extension.compileOptions.sourceCompatibility = JavaVersion.VERSION_17
    extension.compileOptions.targetCompatibility = JavaVersion.VERSION_17
    extension.lint.apply {
        abortOnError = true
        warningsAsErrors = false
        checkDependencies = false
        xmlReport = true
        sarifReport = true
        disable += setOf("GradleDependency", "NewerVersionAvailable", "AndroidGradlePluginVersion")
    }
    extension.testOptions.unitTests.isIncludeAndroidResources = true
    extension.testOptions.unitTests.isReturnDefaultValues = true
    tasks.withType<Test>().configureEach {
        maxHeapSize = "1g"
        systemProperty("robolectric.logging.enabled", "false")
    }
    applyQuality()
}

/** ktlint (formatting) and detekt (static analysis); configured once in the root build script. */
internal fun Project.applyQuality() {
    pluginManager.apply("org.jlleitschuh.gradle.ktlint")
    pluginManager.apply("dev.detekt")
}

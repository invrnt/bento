buildscript {
    dependencies {
        // AGP 9 uses built-in Kotlin and would default to an older Kotlin Gradle plugin: pin it.
        classpath(libs.kotlin.gradle.plugin)
    }
}

plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.android.test) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    alias(libs.plugins.ksp) apply false
    alias(libs.plugins.hilt) apply false
    alias(libs.plugins.chaquopy) apply false
    alias(libs.plugins.roborazzi) apply false
    alias(libs.plugins.ktlint) apply false
    alias(libs.plugins.detekt) apply false
}

// Quality gates: the convention plugins apply ktlint and detekt; they are configured once here.
val ktlintCliVersion = libs.versions.ktlint.cli.get()
subprojects {
    plugins.withId("org.jlleitschuh.gradle.ktlint") {
        configure<org.jlleitschuh.gradle.ktlint.KtlintExtension> {
            version.set(ktlintCliVersion)
            android.set(true)
            filter {
                exclude { it.file.path.contains("/build/") }
            }
        }
    }
    plugins.withId("dev.detekt") {
        configure<dev.detekt.gradle.extensions.DetektExtension> {
            buildUponDefaultConfig.set(true)
            config.setFrom(rootProject.file("config/detekt/detekt.yml"))
            baseline.set(file("detekt-baseline.xml"))
            parallel.set(true)
        }
    }
}

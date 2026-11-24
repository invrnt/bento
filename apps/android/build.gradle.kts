buildscript {
    dependencies {
        // AGP 9 uses built-in Kotlin; pin the Kotlin Gradle plugins explicitly (see docs/dev/android-spike.md).
        classpath(libs.kotlin.gradle.plugin)
        classpath(libs.kotlin.compose.gradle.plugin)
    }
}
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.android.lint) apply false
    alias(libs.plugins.roborazzi) apply false
}

plugins {
    alias(libs.plugins.bento.android.library)
    alias(libs.plugins.bento.android.compose)
}

android {
    namespace = "dev.bento.testing"
}

dependencies {
    api(project(":core:engine"))
    api(project(":core:api"))
    api(libs.kotlinx.coroutines.test)
    api(libs.junit4)

    // Feature screenshot harness (BentoScreenshots): every screen state in light/dark/200 %/compact/expanded.
    api(project(":core:designsystem"))
    api(libs.compose.ui.test.junit4)
    api(libs.roborazzi)
    api(libs.roborazzi.compose)
}

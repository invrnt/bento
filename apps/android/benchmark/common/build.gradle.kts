plugins {
    alias(libs.plugins.bento.android.library)
}

// Shared by :baselineprofile and :benchmark: drives the app from the test process (shell, loopback API with the fake
// cloud, UiAutomator journeys) so the profile generator and the benchmarks exercise exactly the same paths.
android {
    namespace = "dev.bento.benchmark.common"
}

dependencies {
    api(libs.androidx.benchmark.macro)
    api(libs.androidx.test.uiautomator)
    api(libs.androidx.test.runner)
    api(libs.androidx.test.ext.junit)
    implementation(libs.androidx.exifinterface)
    implementation(libs.okhttp)
    api(libs.kotlinx.serialization.json)
}

plugins {
    alias(libs.plugins.android.test)
    alias(libs.plugins.kotlin.serialization)
}

// Photos journeys measured from another process (product/android.md §13): timeline scroll over a seeded
// library of >= 10,000 photos and viewer open, plus instrumented journey 7. Emulator numbers are indicative;
// agent 42 runs the release matrix with a non-debuggable benchmark build and Baseline Profiles.
android {
    namespace = "dev.bento.feature.photos.benchmark"
    compileSdk = libs.versions.compileSdk.get().toInt()
    compileSdkMinor = libs.versions.compileSdkMinor.get().toInt()
    defaultConfig {
        minSdk = libs.versions.minSdk.get().toInt()
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        testInstrumentationRunnerArguments["androidx.benchmark.suppressErrors"] = "EMULATOR,DEBUGGABLE,LOW-BATTERY,NOT-PROFILEABLE"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    targetProjectPath = ":app"
    experimentalProperties["android.experimental.self-instrumenting"] = true
}

dependencies {
    implementation(libs.androidx.test.runner)
    implementation(libs.androidx.test.ext.junit)
    implementation(libs.androidx.test.uiautomator)
    implementation(libs.androidx.benchmark.macro)
    implementation(libs.androidx.exifinterface)
    implementation(libs.okhttp)
    implementation(libs.kotlinx.serialization.json)
}

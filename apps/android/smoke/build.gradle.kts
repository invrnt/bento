plugins {
    alias(libs.plugins.android.test)
    alias(libs.plugins.kotlin.serialization)
}

// Instrumentation in its own process, driving the app like a user/the system would: cold starts
// (Macrobenchmark smoke) and SIGKILL during an upload. Agent 42 moves the benchmarks into benchmark/.
android {
    namespace = "dev.bento.smoke"
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
    implementation(libs.okhttp)
    implementation(libs.kotlinx.serialization.json)
}

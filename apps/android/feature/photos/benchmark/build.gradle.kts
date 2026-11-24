plugins {
    alias(libs.plugins.android.test)
    alias(libs.plugins.kotlin.serialization)
}

// Instrumented Fotos journeys (7 and the Fotos parts of 1, 2, 5) against the debug app, driven from another process
// with the shared :benchmark-common driver. The §13 Fotos Macrobenchmarks live in apps/android/benchmark.
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
    implementation(project(":benchmark-common"))
}

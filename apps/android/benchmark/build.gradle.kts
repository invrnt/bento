plugins {
    alias(libs.plugins.android.test)
}

// App-wide Macrobenchmarks for product/android.md §13 against the non-debuggable `benchmarkRelease` app variant
// (R8, profileable, fake cloud; created by the Baseline Profile plugin + core/engine). Each benchmark runs with
// CompilationMode.None and Partial(BaselineProfileMode.Require). See docs/dev/android-performance.md.
android {
    namespace = "dev.bento.benchmark"
    compileSdk = libs.versions.compileSdk.get().toInt()
    compileSdkMinor = libs.versions.compileSdkMinor.get().toInt()
    defaultConfig {
        minSdk = libs.versions.minSdk.get().toInt()
        targetSdk = libs.versions.targetSdk.get().toInt()
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        testInstrumentationRunnerArguments["androidx.benchmark.suppressErrors"] = "EMULATOR,LOW-BATTERY"
    }
    buildTypes {
        create("benchmarkRelease") {
            isDebuggable = true
            signingConfig = signingConfigs.getByName("debug")
            matchingFallbacks += listOf("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    targetProjectPath = ":app"
    experimentalProperties["android.experimental.self-instrumenting"] = true
}

// Only benchmarkRelease measures anything meaningful; the debug variant would target the debuggable app.
androidComponents {
    beforeVariants(selector().withBuildType("debug")) { it.enable = false }
}

dependencies {
    implementation(project(":benchmark-common"))
}

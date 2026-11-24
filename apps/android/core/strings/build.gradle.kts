plugins {
    id("com.android.library")
}

android {
    namespace = "dev.bento.strings"
    compileSdk = 36

    defaultConfig {
        minSdk = 29
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    testOptions {
        unitTests.isIncludeAndroidResources = true
    }

    lint {
        // Versions are pinned by the orchestration plan (docs/dev/android-spike.md), not by lint.
        disable += setOf("GradleDependency", "NewerVersionAvailable", "AndroidGradlePluginVersion")
        warningsAsErrors = true
        abortOnError = true
        checkDependencies = false
        // Strings are consumed by other modules; unused-in-this-module is expected.
        disable += "UnusedResources"
    }
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    testImplementation(libs.junit)
}

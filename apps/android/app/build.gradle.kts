plugins {
    alias(libs.plugins.bento.android.application)
    alias(libs.plugins.bento.android.compose)
    alias(libs.plugins.bento.hilt)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.roborazzi)
}

val abis = providers.gradleProperty("bentoAbis").get().split(",").map { it.trim() }.filter { it.isNotEmpty() }

android {
    namespace = "dev.bento.app"

    defaultConfig {
        applicationId = "dev.bento.app"
        versionCode = 1
        versionName = "0.1.0"
        ndk { abiFilters += abis }
        // App Links host for https://<site>/join (owner action: production site_url domain).
        manifestPlaceholders["bentoSiteHost"] = providers.gradleProperty("bentoSiteHost").getOrElse("bento.example")
        buildConfigField("String", "TELEGRAM_API_ID", "\"${providers.gradleProperty("bentoTelegramApiId").getOrElse("")}\"")
        buildConfigField("String", "TELEGRAM_API_HASH", "\"${providers.gradleProperty("bentoTelegramApiHash").getOrElse("")}\"")
        buildConfigField("String", "RELAY_URL", "\"${providers.gradleProperty("bentoRelayUrl").getOrElse("")}\"")
        buildConfigField("String", "SITE_URL", "\"${providers.gradleProperty("bentoSiteUrl").getOrElse("")}\"")
    }

    buildTypes {
        getByName("debug") {
            // The `fake` storage backend and dev endpoint file exist only in debug (core/engine BuildConfig).
            isDebuggable = true
        }
        getByName("release") {
            // Signing/R8 details beyond this baseline belong to agent 42 (release block).
            isMinifyEnabled = true
            isShrinkResources = true
            isDebuggable = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    packaging {
        resources.excludes += setOf("/META-INF/{AL2.0,LGPL2.1}", "/META-INF/LICENSE*", "/META-INF/*.kotlin_module")
    }

    testOptions {
        unitTests.isIncludeAndroidResources = true
    }
}

roborazzi {
    outputDir.set(layout.projectDirectory.dir("src/test/screenshots"))
}

dependencies {
    implementation(project(":core:engine"))
    implementation(project(":core:api"))
    implementation(project(":core:data"))
    implementation(project(":core:background"))
    implementation(project(":core:designsystem"))
    implementation(project(":feature:recovery"))
    implementation(project(":feature:onboarding"))
    implementation(project(":feature:pairing"))
    implementation(project(":feature:devices"))

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.core.splashscreen)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.viewmodel.navigation3)
    implementation(libs.androidx.lifecycle.process)
    implementation(libs.androidx.navigation3.runtime)
    implementation(libs.androidx.navigation3.ui)
    implementation(libs.androidx.hilt.work)
    implementation(libs.androidx.hilt.lifecycle.viewmodel.compose)
    implementation(libs.androidx.profileinstaller)
    implementation(libs.androidx.tracing)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.compose.foundation)
    implementation(libs.compose.material3)
    implementation(libs.kotlinx.serialization.json)
    ksp(libs.androidx.hilt.compiler)

    testImplementation(project(":core:testing"))
    testImplementation(libs.junit4)
    testImplementation(libs.robolectric)
    testImplementation(libs.androidx.test.core)
    testImplementation(libs.compose.ui.test.junit4)
    testImplementation(libs.roborazzi)
    testImplementation(libs.roborazzi.compose)
    testImplementation(libs.roborazzi.junit.rule)
    debugImplementation(libs.compose.ui.test.manifest)

    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.test.rules)
    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.androidx.test.uiautomator)
    androidTestImplementation(libs.kotlinx.coroutines.test)
}

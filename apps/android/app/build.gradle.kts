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

// SEC-10: a release must ship a real, verifiable App Links host (debug keeps the `bento.example` default). Packaging
// a release fails unless `bentoSiteHost` names the production site and `bentoSiteUrl` is `https://<that host>`.
val verifyReleaseSiteHost = tasks.register("verifyReleaseSiteHost") {
    val host = providers.gradleProperty("bentoSiteHost").orElse("")
    val url = providers.gradleProperty("bentoSiteUrl").orElse("")
    doLast {
        val siteHost = host.get().trim().lowercase()
        val placeholder = siteHost.isEmpty() || siteHost == "bento.example" || siteHost.endsWith(".example") ||
            siteHost == "localhost" || !Regex("^[a-z0-9.-]+\\.[a-z]{2,}$").matches(siteHost)
        if (placeholder) {
            throw GradleException("Release builds need -PbentoSiteHost=<production site host> (got '$siteHost'), SEC-10")
        }
        if (url.get().trim().removeSuffix("/").lowercase() != "https://$siteHost") {
            throw GradleException("Release builds need -PbentoSiteUrl=https://$siteHost (SEC-10)")
        }
    }
}
tasks.matching { it.name == "packageRelease" || it.name == "bundleRelease" }.configureEach { dependsOn(verifyReleaseSiteHost) }

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
    implementation(project(":feature:files"))
    implementation(project(":feature:search"))
    implementation(project(":feature:share"))
    implementation(project(":feature:photos"))
    implementation(project(":feature:viewer"))
    implementation(project(":feature:collections"))

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
    // Trust journeys (agent 38): Compose UI driven end to end against the real embedded engine.
    androidTestImplementation(platform(libs.compose.bom))
    androidTestImplementation(libs.compose.ui.test.junit4)
}

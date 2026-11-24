plugins {
    alias(libs.plugins.bento.android.application)
    alias(libs.plugins.bento.android.compose)
    alias(libs.plugins.bento.hilt)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.roborazzi)
}

val abis = providers.gradleProperty("bentoAbis").get().split(",").map { it.trim() }.filter { it.isNotEmpty() }

// Release identity (agent 42): `-PbentoVersion=X.Y.Z`, else the exact `android-vX.Y.Z` tag at HEAD, else 0.1.0.
// versionCode = X·10⁶ + Y·10³ + Z (same formula as core/update ManifestParser.versionCode); both APKs share it.
val bentoVersion: String = providers.gradleProperty("bentoVersion").orNull?.trim()?.takeIf { it.isNotEmpty() }
    ?: providers.exec {
        commandLine("git", "describe", "--tags", "--exact-match", "--match", "android-v*", "HEAD")
        isIgnoreExitValue = true
    }.standardOutput.asText.get().trim().removePrefix("android-v").takeIf { it.isNotEmpty() }
    ?: "0.1.0"
val bentoVersionCode: Int = run {
    val match = Regex("^(0|[1-9]\\d{0,2})\\.(0|[1-9]\\d{0,2})\\.(0|[1-9]\\d{0,2})$").matchEntire(bentoVersion)
        ?: error("bentoVersion must be X.Y.Z with each part below 1000, got '$bentoVersion'")
    val (major, minor, patch) = match.destructured.toList().map { it.toInt() }
    major * 1_000_000 + minor * 1_000 + patch
}

// Release signing from a local keystore; nothing is committed. Gradle properties (~/.gradle/gradle.properties)
// or environment variables. Without them `assembleRelease` produces an unsigned APK (scripts/release.sh refuses it).
fun releaseSetting(property: String, env: String): String? =
    providers.gradleProperty(property).orElse(providers.environmentVariable(env)).orNull?.takeIf { it.isNotBlank() }
val releaseStoreFile = releaseSetting("bentoReleaseStoreFile", "BENTO_ANDROID_KEYSTORE")

android {
    namespace = "dev.bento.app"

    defaultConfig {
        applicationId = "dev.bento.app"
        versionCode = bentoVersionCode
        versionName = bentoVersion
        ndk { abiFilters += abis }
        // App Links host for https://<site>/join (owner action: production site_url domain).
        manifestPlaceholders["bentoSiteHost"] = providers.gradleProperty("bentoSiteHost").getOrElse("bento.example")
        buildConfigField("String", "TELEGRAM_API_ID", "\"${providers.gradleProperty("bentoTelegramApiId").getOrElse("")}\"")
        buildConfigField("String", "TELEGRAM_API_HASH", "\"${providers.gradleProperty("bentoTelegramApiHash").getOrElse("")}\"")
        buildConfigField("String", "RELAY_URL", "\"${providers.gradleProperty("bentoRelayUrl").getOrElse("")}\"")
        buildConfigField("String", "SITE_URL", "\"${providers.gradleProperty("bentoSiteUrl").getOrElse("")}\"")
    }

    signingConfigs {
        if (releaseStoreFile != null) {
            create("release") {
                storeFile = file(releaseStoreFile)
                storePassword = releaseSetting("bentoReleaseStorePassword", "BENTO_ANDROID_KEYSTORE_PASSWORD")
                keyAlias = releaseSetting("bentoReleaseKeyAlias", "BENTO_ANDROID_KEY_ALIAS")
                keyPassword = releaseSetting("bentoReleaseKeyPassword", "BENTO_ANDROID_KEY_PASSWORD")
                // minSdk 29: v2 + v3 (v3 carries the rotation lineage if the key is ever rotated); no JAR signing.
                enableV1Signing = false
                enableV2Signing = true
                enableV3Signing = true
            }
        }
    }

    buildTypes {
        getByName("debug") {
            // The `fake` storage backend and dev endpoint file exist only in debug (core/engine BuildConfig).
            isDebuggable = true
        }
        getByName("release") {
            // R8 full mode (AGP default; never disabled in gradle.properties) with app/proguard-rules.pro.
            isMinifyEnabled = true
            isShrinkResources = true
            isDebuggable = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("release")
            // Reproducible-ish artifacts: no build-time VCS info or dependency metadata blob in the APK.
            vcsInfo.include = false
        }
    }

    dependenciesInfo {
        // The signed dependency-metadata block is only readable by Google Play; sideloaded APKs do not need it.
        includeInApk = false
        includeInBundle = true
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
    implementation(project(":core:update"))
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

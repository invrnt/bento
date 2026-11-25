plugins {
    alias(libs.plugins.bento.android.library)
    alias(libs.plugins.bento.android.compose)
    alias(libs.plugins.bento.hilt)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.roborazzi)
}

// In-app updater (product/android.md §2): the signed manifest is the only network call besides Telegram and the relay.
// The Ed25519 key is the desktop's BENTO_UPDATE_PUBLIC_KEY (raw 32-byte key, base64; comma-separated during a
// rotation). Without it the updater reports Unavailable and never touches the network (debug builds by default).
fun setting(property: String, env: String, default: String = ""): String =
    providers.gradleProperty(property).orElse(providers.environmentVariable(env)).getOrElse(default).trim()

android {
    namespace = "dev.bento.update"
    buildFeatures.buildConfig = true
    defaultConfig {
        buildConfigField("String", "UPDATE_PUBLIC_KEYS", "\"${setting("bentoUpdatePublicKey", "BENTO_UPDATE_PUBLIC_KEY")}\"")
        buildConfigField(
            "String",
            "UPDATE_FEED_URL",
            "\"${setting("bentoUpdateFeedUrl", "BENTO_UPDATE_FEED_URL", "https://api.github.com/repos/invrnt/bento/releases")}\""
        )
        buildConfigField("String", "UPDATE_REPOSITORY", "\"invrnt/bento\"")
    }

    testOptions {
        unitTests.all {
            it.maxHeapSize = "1536m"
            it.systemProperty("robolectric.graphicsMode", "NATIVE")
            it.systemProperty("robolectric.pixelCopyRenderMode", "hardware")
        }
    }
}

roborazzi {
    outputDir.set(layout.projectDirectory.dir("screenshots"))
}

dependencies {
    api(project(":core:designsystem"))
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.hilt.lifecycle.viewmodel.compose)
    implementation(libs.androidx.work.runtime)
    implementation(libs.androidx.hilt.work)
    ksp(libs.androidx.hilt.compiler)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.okhttp)
    implementation(libs.bouncycastle.bcprov)

    testImplementation(project(":core:testing"))
    testImplementation(libs.okhttp.mockwebserver)
    testImplementation(libs.androidx.test.ext.junit)
    testImplementation(libs.androidx.work.testing)
    debugImplementation(libs.compose.ui.test.manifest)
}

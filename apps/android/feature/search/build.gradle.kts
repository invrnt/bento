plugins {
    alias(libs.plugins.bento.android.library)
    alias(libs.plugins.bento.android.compose)
    alias(libs.plugins.bento.hilt)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.roborazzi)
}

android {
    namespace = "dev.bento.feature.search"

    testOptions {
        unitTests.isIncludeAndroidResources = true
        unitTests.all {
            it.maxHeapSize = "1536m"
            it.systemProperty("robolectric.graphicsMode", "NATIVE")
            it.systemProperty("robolectric.pixelCopyRenderMode", "hardware")
        }
    }
}

roborazzi {
    // Golden screenshots of every screen state are the handoff's visual review artifact.
    outputDir.set(layout.projectDirectory.dir("screenshots"))
}

dependencies {
    api(project(":feature:files"))
    api(project(":core:designsystem"))
    api(project(":core:data"))
    api(project(":core:api"))
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.hilt.lifecycle.viewmodel.compose)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)

    testImplementation(project(":core:testing"))
    testImplementation(libs.androidx.test.ext.junit)
    debugImplementation(libs.compose.ui.test.manifest)
}

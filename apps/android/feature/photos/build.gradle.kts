plugins {
    alias(libs.plugins.bento.android.library)
    alias(libs.plugins.bento.android.compose)
    alias(libs.plugins.bento.hilt)
    alias(libs.plugins.roborazzi)
}

android {
    namespace = "dev.bento.feature.photos"

    // MediaTestHarness (real repositories over FakeApiTransport + a fake Coil loader) for this and the viewer and
    // collections tests.
    testFixtures { enable = true }

    testOptions {
        unitTests.all {
            it.maxHeapSize = "1536m"
            it.systemProperty("robolectric.graphicsMode", "NATIVE")
            it.systemProperty("robolectric.pixelCopyRenderMode", "hardware")
        }
    }
}

roborazzi {
    // Screen-state goldens are the visual review artifact (design-system/android.md §9); they live in git.
    outputDir.set(layout.projectDirectory.dir("screenshots"))
}

dependencies {
    api(project(":core:data"))
    api(project(":core:designsystem"))
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.hilt.lifecycle.viewmodel.compose)
    api(libs.androidx.paging.compose)
    implementation(libs.androidx.navigation3.ui)
    implementation(libs.androidx.metrics.performance)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.compose.animation)
    implementation(libs.kotlinx.coroutines.android)

    testFixturesImplementation(project(":core:testing"))
    testFixturesImplementation(libs.coil.test)
    testFixturesImplementation(libs.okhttp)
    testFixturesImplementation(platform(libs.compose.bom))
    testFixturesImplementation(libs.compose.ui.test.junit4)
    testFixturesImplementation(libs.androidx.test.core)
    testFixturesImplementation(libs.roborazzi)
    testFixturesImplementation(libs.roborazzi.compose)
    testImplementation(project(":core:testing"))
    testImplementation(libs.compose.ui.test.junit4)
    testImplementation(libs.androidx.test.ext.junit)
    testImplementation(libs.androidx.activity.compose)
    testImplementation(libs.androidx.paging.testing)
    testImplementation(libs.roborazzi)
    testImplementation(libs.roborazzi.compose)
    testImplementation(libs.roborazzi.junit.rule)
    testImplementation(libs.coil.test)
    debugImplementation(libs.compose.ui.test.manifest)
}

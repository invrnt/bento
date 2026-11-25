plugins {
    alias(libs.plugins.bento.android.library)
    alias(libs.plugins.bento.hilt)
}

android {
    namespace = "dev.bento.background"
}

dependencies {
    api(project(":core:engine"))
    // Notification icon (ic_stat_bento) and the notification strings (core/strings).
    implementation(project(":core:designsystem"))
    api(libs.androidx.work.runtime)
    implementation(libs.androidx.core.ktx)
    // Launcher shortcuts (agent 41): photo picker and on-device document scanner trampolines.
    implementation(libs.androidx.activity.compose)
    implementation(libs.mlkit.document.scanner)
    implementation(libs.androidx.hilt.work)
    ksp(libs.androidx.hilt.compiler)
    implementation(libs.kotlinx.coroutines.android)

    testImplementation(project(":core:testing"))
    testImplementation(libs.androidx.work.testing)
    testImplementation(libs.androidx.test.core)
}

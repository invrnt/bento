plugins {
    alias(libs.plugins.bento.android.library)
    alias(libs.plugins.bento.hilt)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "dev.bento.data"
}

dependencies {
    api(project(":core:api"))
    api(libs.androidx.paging.runtime)
    implementation(libs.kotlinx.coroutines.android)

    testImplementation(project(":core:testing"))
    testImplementation(libs.androidx.paging.testing)
}

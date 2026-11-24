plugins {
    alias(libs.plugins.bento.android.library)
    alias(libs.plugins.bento.hilt)
    alias(libs.plugins.bento.openapi)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "dev.bento.api"
}

bentoOpenApi {
    backendProject.set(rootProject.layout.projectDirectory.dir("../api"))
    packageName.set("dev.bento.api.generated")
    // Binary or multipart operations: hand-written in BinaryEndpoints / Coil / Media3.
    excludedOperations.set(
        setOf(
            "uploadAsset",
            "assetThumbnail",
            "assetPreview",
            "assetContent",
            "downloadAsset",
            "avatar",
        ),
    )
}

dependencies {
    api(project(":core:engine"))
    api(libs.okhttp)
    api(libs.kotlinx.serialization.json)
    api(libs.coil.compose)
    implementation(libs.coil.network.okhttp)
    api(libs.media3.datasource.okhttp)
    implementation(libs.kotlinx.coroutines.android)

    testImplementation(project(":core:testing"))
    testImplementation(libs.okhttp.mockwebserver)
}

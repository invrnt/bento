plugins {
    `kotlin-dsl`
}

group = "dev.bento.buildlogic"

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

dependencies {
    // Only AGP's public API is referenced; Kotlin/KSP/Hilt plugins are applied by id so the build-logic
    // compiler (Gradle's embedded Kotlin) never reads Kotlin 2.4 plugin metadata.
    compileOnly(libs.android.gradle.plugin)
    testImplementation(libs.junit4)
}

gradlePlugin {
    plugins {
        register("androidApplication") {
            id = "bento.android.application"
            implementationClass = "dev.bento.buildlogic.AndroidApplicationConventionPlugin"
        }
        register("androidLibrary") {
            id = "bento.android.library"
            implementationClass = "dev.bento.buildlogic.AndroidLibraryConventionPlugin"
        }
        register("androidCompose") {
            id = "bento.android.compose"
            implementationClass = "dev.bento.buildlogic.AndroidComposeConventionPlugin"
        }
        register("hilt") {
            id = "bento.hilt"
            implementationClass = "dev.bento.buildlogic.HiltConventionPlugin"
        }
        register("openApi") {
            id = "bento.openapi"
            implementationClass = "dev.bento.buildlogic.OpenApiConventionPlugin"
        }
    }
}

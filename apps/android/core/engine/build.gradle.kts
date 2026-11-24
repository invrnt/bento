plugins {
    alias(libs.plugins.bento.android.library)
    alias(libs.plugins.bento.hilt)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.chaquopy)
}

val backendRoot = rootProject.layout.projectDirectory.dir("../api")
val wheelsDir = rootProject.layout.projectDirectory.dir("python-wheels")
val generatedPython = layout.buildDirectory.dir("generated/bento-python")
// Chaquopy needs ndk.abiFilters (it refuses AGP ABI splits): CI passes -PbentoAbis=arm64-v8a,x86_64.
val abis = providers.gradleProperty("bentoAbis").get().split(",").map { it.trim() }.filter { it.isNotEmpty() }

android {
    namespace = "dev.bento.engine"
    defaultConfig {
        ndk { abiFilters += abis }
    }
    // `fake` storage, debug options and the dev endpoint file exist only in debug builds.
    buildFeatures.buildConfig = true
    buildTypes {
        getByName("debug") { buildConfigField("boolean", "ENGINE_DEBUG_TOOLS", "true") }
        getByName("release") { buildConfigField("boolean", "ENGINE_DEBUG_TOOLS", "false") }
    }
}

// The backend source set is apps/api/src itself, filtered by python-include.txt (no checked-in copy).
val pythonInclude = layout.projectDirectory.file("python-include.txt")
val syncBackendPython by tasks.registering(Sync::class) {
    val patterns = pythonInclude.asFile.readLines().map { it.trim() }.filter { it.isNotEmpty() && !it.startsWith("#") }
    inputs.file(pythonInclude)
    from(backendRoot.dir("src")) {
        include(patterns.filterNot { it.startsWith("!") })
        exclude(patterns.filter { it.startsWith("!") }.map { it.removePrefix("!") })
    }
    into(layout.buildDirectory.dir("generated/bento-backend-python"))
}

// Alembic needs alembic.ini + migrations/ on the filesystem: ship them as an extracted package.
// TEMPORARY (until agent 35 ships migrations inside the bento package).
val copyBentoMigrations by tasks.registering(Sync::class) {
    from(backendRoot.dir("migrations")) {
        into("bento_migrations/migrations")
        exclude("**/__pycache__/**")
    }
    from(backendRoot.file("alembic.ini")) { into("bento_migrations") }
    from(layout.projectDirectory.file("src/main/python-migrations/__init__.py")) { into("bento_migrations") }
    into(generatedPython)
}

chaquopy {
    defaultConfig {
        version = libs.versions.python.get()
        buildPython(providers.gradleProperty("bentoBuildPython").getOrElse("python3.13"))
        pip {
            options("--find-links", wheelsDir.dir("dist").asFile.absolutePath)
            install("-r", wheelsDir.file("requirements-android.txt").asFile.absolutePath)
        }
        extractPackages("bento_migrations")
    }
    sourceSets {
        getByName("main") {
            // The backend package itself, unchanged (architecture/android-runtime.md §4).
            srcDir(layout.buildDirectory.dir("generated/bento-backend-python").get().asFile)
            srcDir(generatedPython.get().asFile)
            srcDir("src/main/python")
        }
    }
}

tasks.configureEach {
    if (name.startsWith("merge") && name.contains("Python")) dependsOn(copyBentoMigrations, syncBackendPython)
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.service)
    implementation(libs.androidx.exifinterface)
    implementation(libs.androidx.tracing)
    implementation(libs.kotlinx.coroutines.android)
    api(libs.kotlinx.coroutines.core)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.mlkit.text.recognition)

    testImplementation(project(":core:testing"))
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.kotlinx.coroutines.test)
}

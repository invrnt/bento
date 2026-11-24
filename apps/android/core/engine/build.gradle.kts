plugins {
    alias(libs.plugins.bento.android.library)
    alias(libs.plugins.bento.hilt)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.chaquopy)
}

val backendRoot = rootProject.layout.projectDirectory.dir("../api")
val wheelsDir = rootProject.layout.projectDirectory.dir("python-wheels")
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

// Alembic needs migrations/ on the filesystem: they ship as assets (`bento-migrations/`), MigrationAssets copies
// them to noBackupFilesDir once per install and `configure` passes that directory as `migrations_dir`.
abstract class SyncMigrationAssets : DefaultTask() {
    @get:InputDirectory
    @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val migrations: DirectoryProperty

    @get:OutputDirectory
    abstract val output: DirectoryProperty

    @get:javax.inject.Inject
    abstract val fs: FileSystemOperations

    @TaskAction
    fun sync() {
        fs.sync {
            from(migrations) {
                exclude("**/__pycache__/**")
                into("bento-migrations")
            }
            into(output)
        }
    }
}

val syncMigrationAssets by tasks.registering(SyncMigrationAssets::class) {
    migrations.set(backendRoot.dir("migrations"))
    output.set(layout.buildDirectory.dir("generated/bento-migrations-assets"))
}
androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(syncMigrationAssets, SyncMigrationAssets::output)
    }
}

chaquopy {
    defaultConfig {
        version = libs.versions.python.get()
        buildPython(providers.gradleProperty("bentoBuildPython").getOrElse("python3.13"))
        pip {
            options("--find-links", wheelsDir.dir("dist").asFile.absolutePath)
            install("-r", wheelsDir.file("requirements-android.txt").asFile.absolutePath)
        }
    }
    sourceSets {
        getByName("main") {
            // The backend package itself, unchanged (architecture/android-runtime.md §4).
            srcDir(layout.buildDirectory.dir("generated/bento-backend-python").get().asFile)
        }
    }
}

tasks.configureEach {
    if (name.startsWith("merge") && name.contains("Python")) dependsOn(syncBackendPython)
}

// requirements-android.txt must match `uv export --extra android` of apps/api (python-wheels/README.md).
val checkPythonRequirements by tasks.registering(Exec::class) {
    group = "verification"
    description = "Fails when python-wheels/requirements-android.txt is stale versus apps/api/uv.lock."
    workingDir = rootProject.layout.projectDirectory.asFile
    commandLine(
        "uv", "run", "--quiet", "--project", backendRoot.asFile.absolutePath, "--extra", "dev",
        "python", "python-wheels/generate_requirements.py", "--check"
    )
}
tasks.named("check") { dependsOn(checkPythonRequirements) }

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

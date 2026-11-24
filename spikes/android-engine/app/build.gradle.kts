plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

val backendRoot = rootProject.layout.projectDirectory.dir("../../apps/api")
val generatedPython = layout.buildDirectory.dir("generated/bento-python")

android {
    namespace = "dev.bento.spike"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.bento.spike"
        minSdk = 29
        targetSdk = 36
        versionCode = 1
        versionName = "0.0.1-spike"
        ndk {
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }

    // One APK per ABI so each can be sized separately (`apkanalyzer apk download-size`).
    splits {
        abi {
            isEnable = providers.gradleProperty("bentoAbiSplits").map { it.toBoolean() }.getOrElse(false)
            reset()
            include("arm64-v8a", "x86_64")
            isUniversalApk = false
        }
    }

    buildTypes {
        // The spike measures the release-shaped build; it stays debuggable so `run-as` can read results.
        getByName("release") {
            isMinifyEnabled = false
            isDebuggable = true
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    jvmToolchain(17)
}

// Alembic needs `alembic.ini` + `migrations/` on the filesystem: ship them as an extracted package.
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
        version = "3.13"
        buildPython(providers.gradleProperty("bentoBuildPython").getOrElse("python3.13"))
        pip {
            options("--find-links", rootProject.file("wheels/dist").absolutePath)
            install("-r", rootProject.file("requirements-android.txt").absolutePath)
            if (providers.gradleProperty("bentoCryptg").map { it.toBoolean() }.getOrElse(true)) {
                install("cryptg")
            }
        }
        extractPackages("bento_migrations")
    }
    sourceSets {
        getByName("main") {
            // The backend package itself, unchanged (architecture/android-runtime.md §4).
            srcDir(backendRoot.dir("src"))
            srcDir(generatedPython)
        }
    }
}

tasks.configureEach {
    if (name.contains("Python", ignoreCase = false) && name.startsWith("merge")) {
        dependsOn(copyBentoMigrations)
    }
}

dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}

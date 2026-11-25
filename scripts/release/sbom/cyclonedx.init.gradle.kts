// Applied only by scripts/release (`--init-script`): CycloneDX SBOM of the Android app's release runtime
// dependencies without changing the Android build. Plugin version pinned. bento-release runs :app:cyclonedxDirectBom
// (output app/build/reports/cyclonedx-direct/bom.json).
import org.cyclonedx.gradle.CyclonedxDirectTask
import org.cyclonedx.gradle.CyclonedxPlugin

initscript {
    repositories {
        gradlePluginPortal()
    }
    dependencies {
        classpath("org.cyclonedx.bom:org.cyclonedx.bom.gradle.plugin:3.6.1")
    }
}

rootProject {
    apply<CyclonedxPlugin>()
    allprojects {
        tasks.withType<CyclonedxDirectTask>().configureEach {
            // What ships in the APK: release runtime classpaths only (no tests, lint, build tooling).
            includeConfigs.set(listOf("releaseRuntimeClasspath"))
            failOnUnresolvedDependencies.set(true)
        }
    }
}

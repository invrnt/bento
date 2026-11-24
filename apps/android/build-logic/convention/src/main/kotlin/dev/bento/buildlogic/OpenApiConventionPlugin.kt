package dev.bento.buildlogic

import com.android.build.api.variant.LibraryAndroidComponentsExtension
import groovy.json.JsonSlurper
import org.gradle.api.DefaultTask
import org.gradle.api.GradleException
import org.gradle.api.Plugin
import org.gradle.api.Project
import org.gradle.api.file.DirectoryProperty
import org.gradle.api.file.RegularFileProperty
import org.gradle.api.provider.Property
import org.gradle.api.provider.SetProperty
import org.gradle.api.tasks.CacheableTask
import org.gradle.api.tasks.Exec
import org.gradle.api.tasks.Input
import org.gradle.api.tasks.InputFile
import org.gradle.api.tasks.OutputDirectory
import org.gradle.api.tasks.PathSensitive
import org.gradle.api.tasks.PathSensitivity
import org.gradle.api.tasks.TaskAction
import org.gradle.kotlin.dsl.create
import org.gradle.kotlin.dsl.getByType
import org.gradle.kotlin.dsl.register

interface BentoOpenApiExtension {
    /** Checked-in snapshot (`core/api/openapi.json`). */
    val snapshot: RegularFileProperty

    /** `apps/api` (the uv project that exports the schema). */
    val backendProject: DirectoryProperty

    /** Python module (run with `-m`) that prints the deterministic schema to stdout. */
    val exportModule: Property<String>
    val packageName: Property<String>
    val excludedOperations: SetProperty<String>
}

@CacheableTask
abstract class GenerateOpenApiKotlinTask : DefaultTask() {
    @get:InputFile
    @get:PathSensitive(PathSensitivity.NONE)
    abstract val snapshot: RegularFileProperty

    @get:Input
    abstract val packageName: Property<String>

    @get:Input
    abstract val excludedOperations: SetProperty<String>

    @get:OutputDirectory
    abstract val outputDir: DirectoryProperty

    @TaskAction
    fun generate() {
        @Suppress("UNCHECKED_CAST")
        val spec = JsonSlurper().parse(snapshot.get().asFile) as Map<String, Any?>
        val files = OpenApiKotlinGenerator(spec, packageName.get(), excludedOperations.get()).generate()
        val root = outputDir.get().asFile
        root.deleteRecursively()
        val packageDir = root.resolve(packageName.get().replace('.', '/'))
        packageDir.mkdirs()
        files.forEach { (name, content) -> packageDir.resolve(name).writeText(content) }
    }
}

/**
 * `generateOpenApiKotlin` (part of every build), `exportOpenApi` (needs `uv`), `checkOpenApiDrift`
 * (fails when the snapshot differs from the backend), and `updateOpenApiSnapshot`.
 */
class OpenApiConventionPlugin : Plugin<Project> {
    override fun apply(target: Project): Unit = with(target) {
        val extension = extensions.create<BentoOpenApiExtension>("bentoOpenApi")
        extension.snapshot.convention(layout.projectDirectory.file("openapi.json"))
        extension.exportModule.convention("bento.interfaces.http.export_openapi")
        extension.excludedOperations.convention(emptySet())

        val generate = tasks.register<GenerateOpenApiKotlinTask>("generateOpenApiKotlin") {
            group = "bento"
            description = "Generates DTOs and endpoints from the OpenAPI snapshot."
            snapshot.set(extension.snapshot)
            packageName.set(extension.packageName)
            excludedOperations.set(extension.excludedOperations)
            outputDir.set(layout.buildDirectory.dir("generated/openapi/kotlin"))
        }
        extensions.getByType<LibraryAndroidComponentsExtension>().onVariants { variant ->
            variant.sources.kotlin?.addGeneratedSourceDirectory(generate, GenerateOpenApiKotlinTask::outputDir)
        }

        val exported = layout.buildDirectory.file("openapi/backend-openapi.json")
        val export = tasks.register<Exec>("exportOpenApi") {
            group = "bento"
            description = "Exports the backend schema (bento.interfaces.http.export_openapi) with uv."
            val output = exported.get().asFile
            inputs.dir(extension.backendProject.dir("src"))
            inputs.property("module", extension.exportModule)
            outputs.file(output)
            doFirst {
                output.parentFile.mkdirs()
                standardOutput = output.outputStream()
            }
            doLast { standardOutput.close() }
            commandLine(
                "uv", "run", "--quiet", "--project", extension.backendProject.get().asFile.absolutePath,
                "python", "-m", extension.exportModule.get(),
            )
            workingDir(extension.backendProject)
        }
        val drift = tasks.register("checkOpenApiDrift") {
            group = "verification"
            description = "Fails when core/api/openapi.json is stale versus the backend."
            dependsOn(export)
            val snapshotFile = extension.snapshot
            doLast {
                val current = exported.get().asFile.readText()
                val checkedIn = snapshotFile.get().asFile.readText()
                if (current != checkedIn) {
                    throw GradleException(
                        "core/api/openapi.json is stale versus apps/api. Run ./gradlew :core:api:updateOpenApiSnapshot " +
                            "and commit the result.",
                    )
                }
            }
        }
        tasks.named("check") { dependsOn(drift) }
        tasks.register("updateOpenApiSnapshot") {
            group = "bento"
            description = "Rewrites core/api/openapi.json from the backend."
            dependsOn(export)
            val snapshotFile = extension.snapshot
            doLast { exported.get().asFile.copyTo(snapshotFile.get().asFile, overwrite = true) }
        }
        Unit
    }
}

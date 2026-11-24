package dev.bento.buildlogic

import com.android.build.api.dsl.CommonExtension
import org.gradle.api.Plugin
import org.gradle.api.Project

class AndroidComposeConventionPlugin : Plugin<Project> {
    override fun apply(target: Project): Unit = with(target) {
        pluginManager.apply("org.jetbrains.kotlin.plugin.compose")
        val android = extensions.getByName("android") as CommonExtension
        android.buildFeatures.compose = true
        val bom = dependencies.platform(libs.lib("compose-bom"))
        dependencies.add("implementation", bom)
        dependencies.add("androidTestImplementation", bom)
        dependencies.add("testImplementation", bom)
        dependencies.add("implementation", libs.lib("compose-ui"))
        dependencies.add("implementation", libs.lib("compose-ui-tooling-preview"))
        dependencies.add("debugImplementation", libs.lib("compose-ui-tooling"))
    }
}

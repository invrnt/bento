package dev.bento.buildlogic

import com.android.build.api.dsl.LibraryExtension
import org.gradle.api.Plugin
import org.gradle.api.Project
import org.gradle.kotlin.dsl.configure

class AndroidLibraryConventionPlugin : Plugin<Project> {
    override fun apply(target: Project): Unit = with(target) {
        pluginManager.apply("com.android.library")
        extensions.configure<LibraryExtension> {
            configureAndroidCommon(this)
            defaultConfig.testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
            defaultConfig.consumerProguardFiles("consumer-rules.pro")
            testOptions.targetSdk = libs.version("targetSdk").toInt()
            lint.targetSdk = libs.version("targetSdk").toInt()
        }
        dependencies.add("testImplementation", libs.lib("junit4"))
        dependencies.add("testImplementation", libs.lib("kotlinx-coroutines-test"))
        dependencies.add("testImplementation", libs.lib("turbine"))
        dependencies.add("testImplementation", libs.lib("robolectric"))
        dependencies.add("testImplementation", libs.lib("androidx-test-core"))
    }
}

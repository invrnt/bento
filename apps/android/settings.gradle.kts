pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "bento-android"

include(":core:strings")
include(":core:designsystem")
include(":core:designsystem-lint")
project(":core:designsystem-lint").projectDir = file("core/designsystem/lint")

pluginManagement {
    includeBuild("build-logic")
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

include(":app")
include(":core:engine")
include(":core:api")
include(":core:data")
include(":core:background")
include(":core:testing")
include(":smoke")
include(":core:strings")
include(":core:designsystem")
include(":core:designsystem-lint")
project(":core:designsystem-lint").projectDir = file("core/designsystem/lint")
include(":feature:recovery")
include(":feature:onboarding")
include(":feature:pairing")
include(":feature:devices")
include(":feature:files")
include(":feature:search")
include(":feature:share")
include(":feature:photos")
include(":feature:viewer")
include(":feature:collections")
include(":feature:photos-benchmark")
project(":feature:photos-benchmark").projectDir = file("feature/photos/benchmark")

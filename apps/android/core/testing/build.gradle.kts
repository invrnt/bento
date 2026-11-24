plugins {
    alias(libs.plugins.bento.android.library)
}

android {
    namespace = "dev.bento.testing"
}

dependencies {
    api(project(":core:engine"))
    api(project(":core:api"))
    api(libs.kotlinx.coroutines.test)
    api(libs.junit4)
}

plugins {
    alias(libs.plugins.bento.android.library)
}

android {
    namespace = "dev.bento.strings"

    lint {
        warningsAsErrors = true
        // Strings are consumed by other modules; unused-in-this-module is expected.
        disable += "UnusedResources"
    }
}

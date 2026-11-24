buildscript {
    dependencies {
        // AGP 9 uses built-in Kotlin; pin the Kotlin Gradle plugin explicitly.
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.4.21")
    }
}
plugins {
    id("com.android.application") version "9.5.2" apply false
    id("com.chaquo.python") version "17.2.0" apply false
}

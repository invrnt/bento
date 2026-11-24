package dev.bento.update.ui

import dev.bento.update.UpdateAsset
import dev.bento.update.UpdateRelease

val release130 = UpdateRelease(
    version = "1.3.0",
    versionCode = 1_003_000,
    notes = "Actualización estable de Bento 1.3.0.",
    sizeBytes = 96_400_000,
    asset = UpdateAsset(
        platform = "android",
        arch = "arm64",
        kind = "apk",
        filename = "bento-android-1.3.0-arm64-v8a.apk",
        url = "https://example.invalid/a.apk",
        sha256 = "a".repeat(64),
        size = 96_400_000
    ),
    signingCertificates = setOf("a".repeat(64))
)

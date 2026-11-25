# Release rules (agent 42). R8 runs in full mode (AGP default). Libraries ship their own consumer rules (Chaquopy,
# Hilt/Dagger, AndroidX, Media3, CameraX, ML Kit, OkHttp, Coil, kotlinx.serialization); this file covers what they
# cannot know about Bento. Verify a change with `scripts/release.sh --dry-run` (it inspects the R8 output).

-keepattributes *Annotation*, InnerClasses, Signature, EnclosingMethod
# Readable stack traces with the archived mapping.txt.
-keepattributes SourceFile, LineNumberTable
-renamesourcefileattribute SourceFile

# --- Chaquopy: Python calls Kotlin by name -----------------------------------------------------------------------
# The bridges handed to Python (core/engine BridgeSet) are kept by core/engine/consumer-rules.pro. Anything else
# Python reaches through `java`/`jclass` must be listed here; today nothing does (grep `jclass` in apps/api/src).
-keep class com.chaquo.python.** { *; }
-dontwarn com.chaquo.python.**

# --- kotlinx.serialization ----------------------------------------------------------------------------------------
# Generated OpenAPI DTOs (core/api) and every Bento @Serializable class: keep the companion serializer accessors
# that full mode would otherwise strip from classes only reached through serializer<T>().
-keepclassmembers class dev.bento.api.generated.** { *** Companion; kotlinx.serialization.KSerializer serializer(...); }
-keep,includedescriptorclasses class dev.bento.api.generated.**$$serializer { *; }
-if @kotlinx.serialization.Serializable class dev.bento.**
-keepclassmembers class <1> { static <1>$Companion Companion; }
-if @kotlinx.serialization.Serializable class dev.bento.** { static **$* *; }
-keepclassmembers class <2>$<3> { kotlinx.serialization.KSerializer serializer(...); }
-if @kotlinx.serialization.Serializable class dev.bento.**
-keepclassmembers class <1> { kotlinx.serialization.KSerializer serializer(...); }

# --- Media3 --------------------------------------------------------------------------------------------------------
# Media3's consumer rules keep the reflectively probed decoders/extensions; none are bundled, nothing to add.

# --- Hilt / WorkManager --------------------------------------------------------------------------------------------
# Hilt workers are created by name through HiltWorkerFactory.
-keep class * extends androidx.work.ListenableWorker { <init>(android.content.Context, androidx.work.WorkerParameters); }

# --- CameraX / ML Kit ----------------------------------------------------------------------------------------------
# Covered by their consumer rules (bundled barcode/text models load through registered components).

# --- BouncyCastle (core/update Ed25519 only) -------------------------------------------------------------------------
# Only org.bouncycastle.math.ec.rfc8032 is reached; the rest of bcprov references JDK-only APIs.
-dontwarn org.bouncycastle.**
-dontwarn javax.naming.**

# --- Release hygiene ---------------------------------------------------------------------------------------------------
# Verbose/debug logcat calls are compiled out (logs redaction, architecture/android-runtime.md §10).
-assumenosideeffects class android.util.Log {
    public static int v(...);
    public static int d(...);
}

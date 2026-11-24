# Release baseline (agent 42 owns release tuning). Chaquopy contributes its own keep rules.
-keepattributes *Annotation*, InnerClasses, Signature
# kotlinx.serialization generated serializers for DTOs.
-keepclassmembers class dev.bento.api.generated.** { *** Companion; kotlinx.serialization.KSerializer serializer(...); }
-keep,includedescriptorclasses class dev.bento.api.generated.**$$serializer { *; }

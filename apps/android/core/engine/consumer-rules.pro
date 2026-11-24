# Python adapters call the bridges reflectively through Chaquopy: keep every bridge member.
-keep class dev.bento.engine.bridge.** { *; }
-keep interface dev.bento.engine.bridge.** { *; }

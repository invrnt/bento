package dev.bento.engine.di

import android.content.Context
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent
import dev.bento.engine.BentoEngine
import dev.bento.engine.bridge.AndroidMediaTools
import dev.bento.engine.bridge.ContentImportRegistry
import dev.bento.engine.bridge.NotifierHub

/** Engine access for components Hilt cannot inject (QS tile, widgets, instrumented tests). */
@EntryPoint
@InstallIn(SingletonComponent::class)
interface PlatformEntryPoint {
    fun engine(): BentoEngine

    fun mediaTools(): AndroidMediaTools

    fun notifier(): NotifierHub

    fun contentImports(): ContentImportRegistry

    companion object {
        fun get(
            context: Context
        ): PlatformEntryPoint = EntryPointAccessors.fromApplication(context.applicationContext, PlatformEntryPoint::class.java)
    }
}

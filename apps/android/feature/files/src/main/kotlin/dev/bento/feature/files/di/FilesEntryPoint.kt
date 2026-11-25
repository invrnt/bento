package dev.bento.feature.files.di

import android.content.Context
import coil3.ImageLoader
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent
import dev.bento.feature.files.ContentFiles
import dev.bento.feature.files.FilesPreferences
import dev.bento.feature.files.UploadCoordinator

/** Singletons composables reach without a ViewModel (image loader, share sheet, search, Activity). */
@EntryPoint
@InstallIn(SingletonComponent::class)
interface FilesEntryPoint {
    fun imageLoader(): ImageLoader

    fun contentFiles(): ContentFiles

    fun preferences(): FilesPreferences

    fun uploads(): UploadCoordinator

    companion object {
        fun get(
            context: Context
        ): FilesEntryPoint = EntryPointAccessors.fromApplication(context.applicationContext, FilesEntryPoint::class.java)
    }
}

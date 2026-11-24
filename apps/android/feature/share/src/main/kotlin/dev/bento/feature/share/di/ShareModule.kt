package dev.bento.feature.share.di

import android.content.Context
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import dev.bento.feature.share.CacheNoteStore
import dev.bento.feature.share.ContentDescriber
import dev.bento.feature.share.DirectShare
import dev.bento.feature.share.NoteStore
import dev.bento.feature.share.ResolverDescriber
import dev.bento.feature.share.ShortcutDirectShare
import java.io.File

@Module
@InstallIn(SingletonComponent::class)
object ShareModule {
    @Provides
    fun describer(@ApplicationContext context: Context): ContentDescriber = ResolverDescriber(context.contentResolver)

    @Provides
    fun notes(@ApplicationContext context: Context): NoteStore = CacheNoteStore(File(context.cacheDir, "notes"))

    @Provides
    fun directShare(@ApplicationContext context: Context): DirectShare = ShortcutDirectShare(context)
}

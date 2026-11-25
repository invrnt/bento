package dev.bento.feature.search.di

import android.content.Context
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import dev.bento.feature.search.RecentSearches
import dev.bento.feature.search.SharedRecentSearches
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object SearchModule {
    @Provides
    @Singleton
    fun recents(@ApplicationContext context: Context): RecentSearches = SharedRecentSearches.create(context)
}

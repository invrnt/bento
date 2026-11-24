package dev.bento.data.di

import android.content.Context
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import dev.bento.api.EventsClient
import dev.bento.api.generated.BentoEndpoints
import dev.bento.data.ActivityRepository
import dev.bento.data.AlbumsRepository
import dev.bento.data.DevicesRepository
import dev.bento.data.DriveRepository
import dev.bento.data.Invalidations
import dev.bento.data.SearchRepository
import dev.bento.data.SessionRepository
import dev.bento.data.SettingsRepository
import dev.bento.data.TimelineRepository
import dev.bento.data.TrashRepository
import dev.bento.data.UiCache
import dev.bento.engine.di.ApplicationScope
import java.io.File
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope

@Module
@InstallIn(SingletonComponent::class)
object DataModule {
    /** Bumped whenever cached DTO shapes change incompatibly (the drift check regenerates DTOs). */
    private const val UI_CACHE_SCHEMA = "1"

    @Provides
    @Singleton
    fun invalidations(events: EventsClient, @ApplicationScope scope: CoroutineScope): Invalidations =
        Invalidations().also { it.follow(events, scope) }

    @Provides
    @Singleton
    fun uiCache(@ApplicationContext context: Context): UiCache = UiCache(File(context.filesDir, "bento/ui-cache"), UI_CACHE_SCHEMA)

    @Provides
    @Singleton
    fun timeline(api: BentoEndpoints, invalidations: Invalidations, cache: UiCache, @ApplicationScope scope: CoroutineScope) =
        TimelineRepository(api, invalidations, cache, scope)

    @Provides
    @Singleton
    fun drive(api: BentoEndpoints, invalidations: Invalidations, cache: UiCache, @ApplicationScope scope: CoroutineScope) =
        DriveRepository(api, invalidations, cache, scope)

    @Provides
    @Singleton
    fun search(api: BentoEndpoints, invalidations: Invalidations, @ApplicationScope scope: CoroutineScope) =
        SearchRepository(api, invalidations, scope)

    @Provides
    @Singleton
    fun albums(api: BentoEndpoints, invalidations: Invalidations, @ApplicationScope scope: CoroutineScope) =
        AlbumsRepository(api, invalidations, scope)

    @Provides
    @Singleton
    fun trash(api: BentoEndpoints, invalidations: Invalidations, @ApplicationScope scope: CoroutineScope) =
        TrashRepository(api, invalidations, scope)

    @Provides
    @Singleton
    fun activity(api: BentoEndpoints) = ActivityRepository(api)

    @Provides
    @Singleton
    fun devices(api: BentoEndpoints, invalidations: Invalidations) = DevicesRepository(api, invalidations)

    @Provides
    @Singleton
    fun settings(api: BentoEndpoints, invalidations: Invalidations) = SettingsRepository(api, invalidations)

    @Provides
    @Singleton
    fun session(api: BentoEndpoints, cache: UiCache, invalidations: Invalidations) = SessionRepository(api, cache, invalidations)
}

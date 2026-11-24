package dev.bento.app.di

import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import dev.bento.app.BuildConfig
import dev.bento.engine.EngineBuildInfo
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {
    @Provides
    @Singleton
    fun buildInfo(): EngineBuildInfo = EngineBuildInfo(
        appVersion = BuildConfig.VERSION_NAME,
        debugTools = BuildConfig.DEBUG,
        telegramApiId = BuildConfig.TELEGRAM_API_ID,
        telegramApiHash = BuildConfig.TELEGRAM_API_HASH,
        relayUrl = BuildConfig.RELAY_URL,
        siteUrl = BuildConfig.SITE_URL
    )
}

package dev.bento.api.di

import android.content.Context
import coil3.ImageLoader
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import dev.bento.api.BentoHttp
import dev.bento.api.BinaryEndpoints
import dev.bento.api.EngineEndpointProvider
import dev.bento.api.EventsClient
import dev.bento.api.bentoImageLoader
import dev.bento.api.generated.BentoEndpoints
import dev.bento.api.loopbackOkHttp
import dev.bento.engine.BentoEngine
import okhttp3.OkHttpClient
import javax.inject.Qualifier
import javax.inject.Singleton

/** The OkHttp client bound to the loopback API (bearer token attached for the engine origin only). */
@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class LoopbackClient

@Module
@InstallIn(SingletonComponent::class)
object ApiModule {
    @Provides
    @Singleton
    @LoopbackClient
    fun loopbackClient(engine: BentoEngine): OkHttpClient = loopbackOkHttp(engine)

    @Provides
    @Singleton
    fun bentoHttp(@LoopbackClient client: OkHttpClient, engine: BentoEngine): BentoHttp = BentoHttp(client, EngineEndpointProvider(engine))

    @Provides
    @Singleton
    fun endpoints(http: BentoHttp): BentoEndpoints = BentoEndpoints(http)

    @Provides
    @Singleton
    fun binaryEndpoints(http: BentoHttp): BinaryEndpoints = BinaryEndpoints(http)

    @Provides
    @Singleton
    fun events(http: BentoHttp): EventsClient = EventsClient(http)

    @Provides
    @Singleton
    fun imageLoader(@ApplicationContext context: Context, http: BentoHttp, @LoopbackClient client: OkHttpClient): ImageLoader =
        bentoImageLoader(context, http, client)
}

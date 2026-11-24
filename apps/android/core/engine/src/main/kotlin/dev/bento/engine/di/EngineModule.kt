package dev.bento.engine.di

import android.content.Context
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import dev.bento.engine.BentoEngine
import dev.bento.engine.BuildConfig
import dev.bento.engine.ChaquopyEngineRuntime
import dev.bento.engine.DebugOptions
import dev.bento.engine.EngineBuildInfo
import dev.bento.engine.EngineConfigFactory
import dev.bento.engine.EngineLifecycleListener
import dev.bento.engine.EngineLog
import dev.bento.engine.EngineRuntime
import dev.bento.engine.EngineState
import dev.bento.engine.PlatformObservers
import dev.bento.engine.ServiceProcessKeeper
import dev.bento.engine.bridge.AndroidDeviceConditions
import dev.bento.engine.bridge.AndroidKeystoreKeySource
import dev.bento.engine.bridge.AndroidMediaStoreSource
import dev.bento.engine.bridge.AndroidMediaTools
import dev.bento.engine.bridge.BridgeSet
import dev.bento.engine.bridge.ContentImportRegistry
import dev.bento.engine.bridge.ContentResolverDescriptorOpener
import dev.bento.engine.bridge.KeyWrapping
import dev.bento.engine.bridge.KeystoreKeyWrapping
import dev.bento.engine.bridge.MlKitOcr
import dev.bento.engine.bridge.NotifierHub
import java.io.File
import java.util.concurrent.Executors
import javax.inject.Qualifier
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach

/** Application-wide coroutine scope (never cancelled). */
@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class ApplicationScope

@Module
@InstallIn(SingletonComponent::class)
object EngineModule {
    @Provides
    @Singleton
    @ApplicationScope
    fun applicationScope(): CoroutineScope = CoroutineScope(SupervisorJob() + kotlinx.coroutines.Dispatchers.Default)

    @Provides
    @Singleton
    fun engineLog(): EngineLog = if (BuildConfig.ENGINE_DEBUG_TOOLS) EngineLog.Logcat() else EngineLog.None

    @Provides
    @Singleton
    fun mediaTools(): AndroidMediaTools = AndroidMediaTools()

    @Provides
    @Singleton
    fun mediaStore(@ApplicationContext context: Context): AndroidMediaStoreSource = AndroidMediaStoreSource(context)

    @Provides
    @Singleton
    fun conditions(@ApplicationContext context: Context): AndroidDeviceConditions = AndroidDeviceConditions(context)

    @Provides
    @Singleton
    fun notifier(): NotifierHub = NotifierHub()

    @Provides
    @Singleton
    fun contentImports(@ApplicationContext context: Context): ContentImportRegistry =
        ContentImportRegistry(ContentResolverDescriptorOpener(context.contentResolver))

    @Provides
    @Singleton
    fun bridges(
        mediaTools: AndroidMediaTools,
        mediaStore: AndroidMediaStoreSource,
        conditions: AndroidDeviceConditions,
        notifier: NotifierHub,
        contentImports: ContentImportRegistry
    ): BridgeSet = BridgeSet(mediaTools, MlKitOcr(), mediaStore, conditions, notifier, contentImports)

    @Provides
    @Singleton
    fun keyWrapping(@ApplicationContext context: Context): KeyWrapping = KeystoreKeyWrapping(
        file = File(File(context.noBackupFilesDir, "bento/secure"), "wrapping.bin"),
        keySource = AndroidKeystoreKeySource(context.packageManager)
    )

    @Provides
    @Singleton
    fun runtime(@ApplicationContext context: Context, bridges: BridgeSet): EngineRuntime = ChaquopyEngineRuntime(context, bridges)

    @OptIn(ExperimentalCoroutinesApi::class)
    @Provides
    @Singleton
    fun engine(
        @ApplicationContext context: Context,
        runtime: EngineRuntime,
        buildInfo: EngineBuildInfo,
        keyWrapping: KeyWrapping,
        mediaStore: AndroidMediaStoreSource,
        conditions: AndroidDeviceConditions,
        contentImports: ContentImportRegistry,
        log: EngineLog,
        @ApplicationScope scope: CoroutineScope
    ): BentoEngine {
        lateinit var engine: BentoEngine
        val observers = PlatformObservers(mediaStore, conditions) { engine }
        val imports = object : EngineLifecycleListener {
            override fun onEngineRunning() = Unit

            override fun onEngineStopping() = contentImports.clear()
        }
        val dispatcher = Executors.newSingleThreadExecutor { runnable -> Thread(runnable, "bento-engine") }.asCoroutineDispatcher()
        engine = BentoEngine(
            runtime = runtime,
            config = EngineConfigFactory(context, buildInfo)::create,
            wrappingKey = keyWrapping::deviceWrappingKey,
            processKeeper = ServiceProcessKeeper(context, log),
            scope = scope,
            engineDispatcher = dispatcher,
            listeners = setOf(observers, imports),
            log = log
        )
        if (buildInfo.debugTools) {
            engine.state.onEach { state ->
                if (state is EngineState.Ready) DebugOptions.publishEndpoint(context, state) else DebugOptions.clearEndpoint(context)
            }.launchIn(scope)
        }
        return engine
    }
}

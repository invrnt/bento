package dev.bento.feature.files.di

import android.content.Context
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import dev.bento.api.BentoHttp
import dev.bento.api.di.LoopbackClient
import dev.bento.api.generated.BentoEndpoints
import dev.bento.background.TransferScheduler
import dev.bento.data.DriveRepository
import dev.bento.data.Invalidations
import dev.bento.data.UiCache
import dev.bento.engine.BentoEngine
import dev.bento.engine.bridge.AndroidDeviceConditions
import dev.bento.engine.bridge.ContentDescription
import dev.bento.engine.bridge.ContentImportRegistry
import dev.bento.engine.di.ApplicationScope
import dev.bento.feature.files.AndroidPdfSource
import dev.bento.feature.files.AudioControls
import dev.bento.feature.files.AudioPlayer
import dev.bento.feature.files.Connectivity
import dev.bento.feature.files.ContentFiles
import dev.bento.feature.files.ContentHandles
import dev.bento.feature.files.DocumentTreeReader
import dev.bento.feature.files.FilesPreferences
import dev.bento.feature.files.FilesRepository
import dev.bento.feature.files.ImportFailureLog
import dev.bento.feature.files.PdfOpener
import dev.bento.feature.files.SharedFilesPreferences
import dev.bento.feature.files.TransferControl
import dev.bento.feature.files.TreeReader
import dev.bento.feature.files.UploadCoordinator
import dev.bento.feature.files.revokeSharedFile
import java.io.File
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient

@Module
@InstallIn(SingletonComponent::class)
object FilesModule {
    private val json = Json { ignoreUnknownKeys = true }

    @Provides
    @Singleton
    fun preferences(@ApplicationContext context: Context): FilesPreferences = SharedFilesPreferences.create(context)

    @Provides
    @Singleton
    fun repository(
        api: BentoEndpoints,
        http: BentoHttp,
        drive: DriveRepository,
        invalidations: Invalidations,
        uiCache: UiCache
    ): FilesRepository =
        FilesRepository(api, http, drive, invalidations, uiCache)

    @Provides
    @Singleton
    fun connectivity(conditions: AndroidDeviceConditions): Connectivity = Connectivity { conditions.current().online }

    @Provides
    @Singleton
    fun contentFiles(@ApplicationContext context: Context, http: BentoHttp): ContentFiles =
        ContentFiles(http, File(context.cacheDir, "share"), onExpired = { file -> revokeSharedFile(context, file) })
            .also { it.prune(everything = true) }

    @Provides
    @Singleton
    fun failures(@ApplicationContext context: Context): ImportFailureLog = ImportFailureLog(File(context.filesDir, "bento/imports"))

    @Provides
    @Singleton
    fun handles(registry: ContentImportRegistry): ContentHandles = object : ContentHandles {
        override fun register(uri: String): ContentHandles.Registered {
            val handle = registry.register(uri)
            val description = json.decodeFromString(ContentDescription.serializer(), registry.describe(handle))
            return ContentHandles.Registered(handle, description.displayName, description.mimeType, description.sizeBytes)
        }
    }

    @Provides
    @Singleton
    fun transfers(@ApplicationContext context: Context): TransferControl = object : TransferControl {
        override fun start(estimatedBytes: Long) {
            runCatching { TransferScheduler.start(context, estimatedBytes.coerceAtLeast(0)) }
        }

        override fun stop() = TransferScheduler.stop(context)
    }

    @Provides
    @Singleton
    fun uploads(
        api: BentoEndpoints,
        handles: ContentHandles,
        transfers: TransferControl,
        failures: ImportFailureLog,
        invalidations: Invalidations,
        @ApplicationScope scope: CoroutineScope
    ): UploadCoordinator = UploadCoordinator(api, handles, transfers, failures, invalidations, scope)

    @Provides
    fun pdfOpener(): PdfOpener = PdfOpener { file, onClose -> AndroidPdfSource(file, onClose) }

    @Provides
    fun treeReader(@ApplicationContext context: Context): TreeReader = DocumentTreeReader(context.contentResolver)

    @Provides
    @Singleton
    fun audio(@ApplicationContext context: Context, @LoopbackClient client: OkHttpClient, engine: BentoEngine): AudioControls =
        AudioPlayer(context, client, engine)
}

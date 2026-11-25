package dev.bento.update.di

import android.content.Context
import androidx.work.WorkManager
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import dev.bento.update.AndroidPackageInspector
import dev.bento.update.ApkDownloader
import dev.bento.update.BuildConfig
import dev.bento.update.GitHubReleaseFeed
import dev.bento.update.PackageInstallerUpdater
import dev.bento.update.SharedUpdatePreferences
import dev.bento.update.UpdateChecker
import dev.bento.update.UpdateConfig
import dev.bento.update.UpdateScheduler
import dev.bento.update.UpdateSignature
import java.io.File
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

@Module
@InstallIn(SingletonComponent::class)
object UpdateModule {
    @Provides
    @Singleton
    fun updateConfig(): UpdateConfig {
        val feed = BuildConfig.UPDATE_FEED_URL.toHttpUrlOrNull()
        return UpdateConfig(
            publicKeys = if (feed == null) emptyList() else UpdateSignature.parsePublicKeys(BuildConfig.UPDATE_PUBLIC_KEYS),
            repository = BuildConfig.UPDATE_REPOSITORY,
            // Only a local dry-run build points the feed at 127.0.0.1 (apps/android/scripts/release.sh --dry-run).
            allowLoopbackHttp = feed?.host == "127.0.0.1"
        )
    }

    @Provides
    @Singleton
    fun updateChecker(@ApplicationContext context: Context, config: UpdateConfig): UpdateChecker {
        val client = GitHubReleaseFeed.defaultClient()
        return UpdateChecker(
            config = config,
            feed = GitHubReleaseFeed(client, BuildConfig.UPDATE_FEED_URL, config.allowLoopbackHttp),
            downloader = ApkDownloader(client, File(context.noBackupFilesDir, "bento-update")),
            packages = AndroidPackageInspector(context),
            installer = PackageInstallerUpdater(context),
            preferences = SharedUpdatePreferences(context),
            scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
        )
    }

    @Provides
    @Singleton
    fun updateScheduler(@ApplicationContext context: Context, config: UpdateConfig): UpdateScheduler =
        UpdateScheduler(config) { WorkManager.getInstance(context) }
}
